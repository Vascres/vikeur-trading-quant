"""Service journal (correctif du 16/08/2026, découvert en construisant
"Why No Trade") - persiste chaque événement publié sur le canal Redis
`events:journal` dans la table `events_journal`.

Bug pré-existant découvert en creusant les données disponibles pour ce
chantier : la table `events_journal` existe depuis la toute première
migration (0001), avec des index (`time DESC`, `source_module,
event_type`) manifestement prévus pour être interrogée - mais AUCUN
service n'a jamais écrit dedans. Chaque service publie ses événements
sur Redis (pub/sub, éphémère) sans qu'aucun consommateur ne les
persiste. Deux conséquences déjà en production avant ce correctif :
- `GET /logs` (section "Journal" du dashboard) a toujours renvoyé une
  liste vide, silencieusement.
- `monitoring/main.py` (fraîcheur par module, détection de
  déconnexions répétées) interroge cette même table vide depuis le
  début - ses alertes n'ont jamais pu se déclencher, pour aucun module,
  jamais.

Ce service devient le second consommateur du canal `events:journal`
(le premier étant `notifications`, Étape 10) - Redis pub/sub livre le
même message à chaque abonné actif indépendamment (pas une file à
consommateur unique), donc les deux coexistent sans interférence.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import asyncpg
import redis.asyncio as redis

from shared.heartbeat import run_heartbeat

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
JOURNAL_CHANNEL = "events:journal"


def parse_journal_message(raw_data) -> dict | None:
    """Fonction pure, séparée pour être testée sans mock Redis - un
    message illisible ne doit jamais faire tomber le service, seulement
    être ignoré et journalisé localement (même discipline que
    `notifications/main.py::parse_journal_message`, dupliquée plutôt que
    partagée : chaque service de consommation reste autonome, même
    principe que le reste de ce dépôt)."""
    try:
        return json.loads(raw_data)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Événement journal illisible, ignoré : %r", raw_data)
        return None


async def persist_event(db_pool: asyncpg.Pool, event: dict) -> bool:
    """Retourne `False` sans écrire si l'événement est incomplet
    (`source_module`/`event_type` absents) - jamais une ligne à moitié
    remplie en base."""
    source_module = event.get("source_module")
    event_type = event.get("event_type")
    payload = event.get("payload", {})

    if not source_module or not event_type:
        logger.warning("Événement journal incomplet, ignoré : %r", event)
        return False

    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO events_journal (source_module, event_type, payload) VALUES ($1, $2, $3::jsonb);",
            source_module,
            event_type,
            json.dumps(payload, default=str),
        )
    return True


async def consume_and_persist(pubsub, db_pool: asyncpg.Pool) -> None:
    async for message in pubsub.listen():
        if message["type"] != "message":
            continue

        event = parse_journal_message(message["data"])
        if event is None:
            continue

        try:
            await persist_event(db_pool, event)
        except Exception:
            # Ne jamais faire tomber le service pour un seul événement -
            # l'événement suivant doit toujours pouvoir être traité.
            logger.exception("Échec d'écriture d'un événement journal - événement perdu : %r", event)


async def main() -> None:
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
    redis_client = redis.from_url(REDIS_URL)
    asyncio.create_task(run_heartbeat())

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(JOURNAL_CHANNEL)

    await consume_and_persist(pubsub, db_pool)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
