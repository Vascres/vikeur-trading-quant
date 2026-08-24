"""Service notifications (mandat §18, Étape 10 du plan validé le
16/08/2026) - premier consommateur du canal `events:journal` (jusqu'ici,
tous les autres services ne faisaient que publier, jamais s'abonner).

Architecture non-bloquante (mandat, §10-A "Architecture Asynchrone") :
un abonnement Redis pub/sub alimente une file bornée (`asyncio.Queue`,
message le plus ancien supprimé silencieusement si pleine plutôt que de
bloquer) ; une tâche séparée consomme cette file et envoie vers Telegram
- une panne ou une lenteur de l'API Telegram ne peut jamais remonter
jusqu'à la réception des événements.

Limitation assumée (Redis pub/sub, pas un flux persistant type Streams) :
un événement publié pendant que ce service est arrêté est définitivement
perdu, jamais rejouable après coup - cohérent avec l'objectif "temps
réel" du mandat (notifier maintenant, pas archiver un historique
consultable ; l'historique complet reste dans les tables applicatives
elles-mêmes, jamais uniquement dans Telegram).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime

import redis.asyncio as redis

from notifications.channels import Channel, route
from notifications.rate_limiter import Debouncer
from notifications.telegram_client import TelegramClient
from shared.heartbeat import run_heartbeat

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
JOURNAL_CHANNEL = "events:journal"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID_BY_CHANNEL = {
    Channel.ALERTS: os.environ.get("TELEGRAM_CHAT_ID_ALERTS", ""),
    Channel.LIVE: os.environ.get("TELEGRAM_CHAT_ID_LIVE", ""),
    Channel.PAPER: os.environ.get("TELEGRAM_CHAT_ID_PAPER", ""),
}

# File bornée (mandat : "le système supprime les anciens messages
# silencieusement plutôt que de faire crasher Vikeur") - un débit normal
# ne l'approche jamais ; elle protège contre une rafale d'erreurs
# répétées si Telegram devient lent à répondre.
MAX_QUEUE_SIZE = 500


def parse_journal_message(raw_data) -> dict | None:
    """Fonction pure, séparée pour être testée sans mock Redis - un
    message illisible ne doit jamais faire tomber le service, seulement
    être ignoré et journalisé localement."""
    try:
        return json.loads(raw_data)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Événement journal illisible, ignoré : %r", raw_data)
        return None


def enqueue_notification(queue: asyncio.Queue, notification) -> None:
    """Jamais un blocage (mandat) - supprime le plus ancien message de
    la file si elle est pleine plutôt que d'attendre de la place."""
    if queue.full():
        queue.get_nowait()
    queue.put_nowait(notification)


async def enqueue_incoming_events(pubsub, queue: asyncio.Queue, debouncer: Debouncer) -> None:
    async for message in pubsub.listen():
        if message["type"] != "message":
            continue

        event = parse_journal_message(message["data"])
        if event is None:
            continue

        notification = route(
            event.get("event_type", ""), event.get("source_module", ""), event.get("payload", {})
        )
        if notification is None:
            continue

        if notification.should_debounce and not debouncer.should_send(
            notification.dedupe_key, datetime.now(tz=UTC)
        ):
            continue

        enqueue_notification(queue, notification)


async def send_queued_notifications(queue: asyncio.Queue, telegram_client: TelegramClient) -> None:
    while True:
        notification = await queue.get()
        chat_id = CHAT_ID_BY_CHANNEL.get(notification.channel, "")
        if not chat_id:
            logger.warning(
                "Aucun chat_id configuré pour le canal '%s' - notification perdue : %s",
                notification.channel.value,
                notification.text,
            )
            continue
        await telegram_client.send_message(
            chat_id, notification.text, disable_notification=not notification.critical
        )


async def main() -> None:
    redis_client = redis.from_url(REDIS_URL)
    telegram_client = TelegramClient(TELEGRAM_BOT_TOKEN)
    asyncio.create_task(run_heartbeat())

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(JOURNAL_CHANNEL)

    queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
    debouncer = Debouncer()

    alerts_chat_id = CHAT_ID_BY_CHANNEL.get(Channel.ALERTS, "")
    if alerts_chat_id:
        await telegram_client.send_message(alerts_chat_id, "🟢 Service de notifications Vikeur démarré.")

    await asyncio.gather(
        enqueue_incoming_events(pubsub, queue, debouncer),
        send_queued_notifications(queue, telegram_client),
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
