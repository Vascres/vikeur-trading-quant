"""Service monitoring (Phase 19).

Anti-spam : chaque type d'alerte a un cooldown (Phase 19, §4) stocké
dans Redis - une panne persistante alerte une fois, pas en continu.

Correctif du 16/08/2026 (découvert en documentant le projet) : ce
service envoyait ses alertes directement vers Telegram
(`monitoring/alerting.py`, `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`),
un second chemin d'envoi totalement indépendant et inconnu du service
`notifications` (Étape 10, `TELEGRAM_CHAT_ID_ALERTS/LIVE/PAPER`) -
configurer l'un sans l'autre laissait silencieusement les alertes de
`monitoring` sans destination. Consolidé : ce service publie désormais
un événement journalisé (`monitoring.alert_triggered`), relayé par
`notifications` comme tout le reste - une seule configuration Telegram
pour tout le projet, jamais deux.

Ce correctif révèle aussi, en le corrigeant, un second bug pré-existant :
les vérifications de fraîcheur ci-dessous interrogent `events_journal`
(ligne `_run_all_checks`) - une table restée vide depuis toujours avant
le correctif du service `journal` (16/08/2026, cf. son propre docstring).
Les alertes de fraîcheur de ce service n'ont donc jamais pu se
déclencher, pour aucun module, avant ces deux correctifs combinés.
"""

import asyncio
import json
import logging
import os

import asyncpg
import redis.asyncio as redis

from monitoring.health_checks import (
    Alert,
    check_disk_space,
    check_kill_switch,
    check_module_freshness,
    check_reconnection_rate,
)
from shared.heartbeat import run_heartbeat

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]
KILL_SWITCH_REDIS_KEY = "risk:kill_switch"
JOURNAL_CHANNEL = "events:journal"

CHECK_INTERVAL_SECONDS = 60
ALERT_COOLDOWN_SECONDS = 30 * 60

# Fraîcheur attendue par module (Phase 19, §4)
MODULE_FRESHNESS_THRESHOLDS = {
    "data_collector": 5 * 60,
    "data_normalizer": 5 * 60,
    "feature_engine": 3 * 60,
    "decision_engine": 3 * 60,
    "risk_engine": 2 * 60,
    "execution_engine": 2 * 60,
}

MAX_RECONNECTIONS_PER_WINDOW = 5
RECONNECTION_WINDOW_MINUTES = 15


async def main() -> None:
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
    redis_client = redis.from_url(REDIS_URL)
    asyncio.create_task(run_heartbeat())

    def publish_journal_event(event_type: str, payload: dict) -> None:
        asyncio.create_task(
            redis_client.publish(
                JOURNAL_CHANNEL,
                json.dumps(
                    {"source_module": "monitoring", "event_type": event_type, "payload": payload}, default=str
                ),
            )
        )

    while True:
        try:
            await _run_all_checks(db_pool, redis_client, publish_journal_event)
        except Exception:
            logger.exception("Erreur dans la boucle de monitoring")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def _run_all_checks(db_pool: asyncpg.Pool, redis_client: redis.Redis, publish_journal_event) -> None:
    import datetime as dt

    now = dt.datetime.now(tz=dt.UTC)
    alerts: list[Alert] = []

    async with db_pool.acquire() as conn:
        for module_name, max_age in MODULE_FRESHNESS_THRESHOLDS.items():
            last_event = await conn.fetchval(
                "SELECT MAX(time) FROM events_journal WHERE source_module = $1;", module_name
            )
            alert = check_module_freshness(module_name, last_event, now, max_age)
            if alert:
                alerts.append(alert)

        reconnection_count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM events_journal
            WHERE source_module = 'data_collector' AND event_type = 'collector.disconnected'
              AND time >= now() - ($1 || ' minutes')::interval;
            """,
            str(RECONNECTION_WINDOW_MINUTES),
        )

    reconnection_alert = check_reconnection_rate(
        reconnection_count, RECONNECTION_WINDOW_MINUTES, MAX_RECONNECTIONS_PER_WINDOW
    )
    if reconnection_alert:
        alerts.append(reconnection_alert)

    disk_alert = check_disk_space()
    if disk_alert:
        alerts.append(disk_alert)

    kill_switch_raw = await redis_client.get(KILL_SWITCH_REDIS_KEY)
    kill_switch_alert = check_kill_switch(kill_switch_raw == b"1")
    if kill_switch_alert:
        alerts.append(kill_switch_alert)

    for alert in alerts:
        await _send_if_not_in_cooldown(redis_client, alert, publish_journal_event)


async def _send_if_not_in_cooldown(redis_client: redis.Redis, alert: Alert, publish_journal_event) -> None:
    cooldown_key = f"monitoring:cooldown:{alert.check_name}"
    already_sent = await redis_client.get(cooldown_key)
    if already_sent:
        return

    publish_journal_event(
        "monitoring.alert_triggered", {"check_name": alert.check_name, "message": alert.message}
    )
    await redis_client.set(cooldown_key, "1", ex=ALERT_COOLDOWN_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
