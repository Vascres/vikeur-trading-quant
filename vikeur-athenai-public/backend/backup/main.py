"""Service backup (Module 2).

Boucle asynchrone (même style que les autres services, Phase 2/18) -
pas de cron, pas de nouvelle dépendance d'ordonnancement.
"""

import asyncio
import json
import logging
import os
import tempfile

import redis.asyncio as redis

from backup.dump import build_backup_filename, run_pg_dump
from backup.scheduling import seconds_until_next_run
from backup.storage import delete_backups, filter_expired_backups, list_backup_keys, upload_backup
from shared.heartbeat import run_heartbeat

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]
JOURNAL_CHANNEL = "events:journal"
BACKUP_RETENTION_DAYS = int(os.environ.get("BACKUP_RETENTION_DAYS", "30"))
TARGET_HOUR_UTC = int(os.environ.get("BACKUP_HOUR_UTC", "3"))


def _extract_password(database_url: str) -> str:
    # postgresql://user:password@host:port/db
    return database_url.split("://")[1].split(":")[1].split("@")[0]


async def main() -> None:
    redis_client = redis.from_url(REDIS_URL)
    asyncio.create_task(run_heartbeat())

    def publish_journal_event(event_type: str, payload: dict) -> None:
        asyncio.create_task(
            redis_client.publish(
                JOURNAL_CHANNEL,
                json.dumps(
                    {"source_module": "backup", "event_type": event_type, "payload": payload}, default=str
                ),
            )
        )

    publish_journal_event("backup.started", {})

    while True:
        import datetime as dt

        now = dt.datetime.now(tz=dt.UTC)
        wait_seconds = seconds_until_next_run(now, TARGET_HOUR_UTC)
        logger.info("Prochaine sauvegarde dans %.0f secondes", wait_seconds)
        await asyncio.sleep(wait_seconds)

        try:
            await _run_backup_cycle(publish_journal_event)
        except Exception as exc:  # noqa: BLE001 - ne jamais arrêter la boucle
            logger.exception("Échec du cycle de sauvegarde")
            publish_journal_event("backup.failed", {"error": str(exc)})


async def _run_backup_cycle(publish_journal_event) -> None:
    password = _extract_password(DATABASE_URL)

    with tempfile.TemporaryDirectory() as tmp_dir:
        compressed_path = run_pg_dump(DATABASE_URL, password, tmp_dir)
        filename = build_backup_filename()
        upload_backup(compressed_path, filename)

    publish_journal_event("backup.completed", {"filename": filename})

    existing_keys = list_backup_keys()
    import datetime as dt

    expired = filter_expired_backups(existing_keys, dt.datetime.now(tz=dt.UTC), BACKUP_RETENTION_DAYS)
    if expired:
        delete_backups(expired)
        publish_journal_event("backup.retention_cleanup", {"deleted_count": len(expired)})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
