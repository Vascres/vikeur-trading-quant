"""Tests de notifications.main (mandat §18, Étape 10 du plan validé le 16/08/2026)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from notifications.channels import Channel, RoutedNotification
from notifications.main import (
    enqueue_incoming_events,
    enqueue_notification,
    parse_journal_message,
    send_queued_notifications,
)
from notifications.rate_limiter import Debouncer


def test_parse_journal_message_returns_none_on_invalid_json():
    assert parse_journal_message(b"not-json{{{") is None


def test_parse_journal_message_parses_valid_payload():
    raw = json.dumps({"source_module": "api", "event_type": "kill_switch.activated", "payload": {}})
    assert parse_journal_message(raw) == {
        "source_module": "api",
        "event_type": "kill_switch.activated",
        "payload": {},
    }


def test_enqueue_notification_drops_oldest_when_queue_full():
    """Mandat : jamais un blocage - le message le plus ancien est
    supprimé silencieusement pour faire de la place."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=2)
    first = RoutedNotification(Channel.ALERTS, "premier", False, "k1", False)
    second = RoutedNotification(Channel.ALERTS, "deuxième", False, "k2", False)
    third = RoutedNotification(Channel.ALERTS, "troisième", False, "k3", False)

    enqueue_notification(queue, first)
    enqueue_notification(queue, second)
    enqueue_notification(queue, third)

    assert queue.qsize() == 2
    remaining = [queue.get_nowait().text for _ in range(2)]
    assert remaining == ["deuxième", "troisième"]  # le premier a été supprimé, jamais un blocage


class _FakePubSub:
    """Simule `redis.asyncio.client.PubSub.listen()` - un générateur
    asynchrone de messages, sans dépendre d'un vrai serveur Redis."""

    def __init__(self, raw_messages: list[bytes]):
        self._raw_messages = raw_messages

    async def listen(self):
        for raw in self._raw_messages:
            yield {"type": "message", "data": raw}
        # Simule une file qui se termine (pour que le test se termine) -
        # un vrai flux Redis ne se termine jamais, cf. limitation notée
        # dans le docstring du module principal.


def _event(event_type: str, payload: dict | None = None, source_module: str = "api") -> bytes:
    return json.dumps(
        {"source_module": source_module, "event_type": event_type, "payload": payload or {}}
    ).encode()


@pytest.mark.asyncio
async def test_enqueue_incoming_events_routes_recognized_events_into_the_queue():
    pubsub = _FakePubSub([_event("kill_switch.activated", {"active": True})])
    queue: asyncio.Queue = asyncio.Queue(maxsize=10)

    await enqueue_incoming_events(pubsub, queue, Debouncer())

    assert queue.qsize() == 1
    notification = queue.get_nowait()
    assert notification.channel == Channel.ALERTS


@pytest.mark.asyncio
async def test_enqueue_incoming_events_ignores_unrecognized_events():
    pubsub = _FakePubSub([_event("cost_model.started")])
    queue: asyncio.Queue = asyncio.Queue(maxsize=10)

    await enqueue_incoming_events(pubsub, queue, Debouncer())

    assert queue.qsize() == 0


@pytest.mark.asyncio
async def test_enqueue_incoming_events_applies_debounce_to_generic_alerts():
    """Deux erreurs identiques rapprochées -> une seule notification en file."""
    pubsub = _FakePubSub(
        [
            _event("collector.ws_disconnected", {"exchange": "htx"}),
            _event("collector.ws_disconnected", {"exchange": "htx"}),
        ]
    )
    queue: asyncio.Queue = asyncio.Queue(maxsize=10)

    await enqueue_incoming_events(pubsub, queue, Debouncer())

    assert queue.qsize() == 1


@pytest.mark.asyncio
async def test_enqueue_incoming_events_never_debounces_trade_executions():
    """Deux trades réels rapprochés doivent TOUS LES DEUX notifier -
    jamais fusionnés comme des erreurs répétées."""
    trade_payload = {
        "symbol": "BTC/USDT",
        "side": "buy",
        "quantity": "0.01",
        "price": "60000",
        "execution_mode": "real",
    }
    pubsub = _FakePubSub([_event("execution_engine.order_executed", trade_payload)] * 2)
    queue: asyncio.Queue = asyncio.Queue(maxsize=10)

    await enqueue_incoming_events(pubsub, queue, Debouncer())

    assert queue.qsize() == 2


@pytest.mark.asyncio
async def test_enqueue_incoming_events_skips_non_message_types():
    pubsub = _FakePubSub([])
    pubsub._raw_messages = []

    async def fake_listen():
        yield {"type": "subscribe", "data": 1}  # confirmation d'abonnement, jamais un événement

    pubsub.listen = fake_listen
    queue: asyncio.Queue = asyncio.Queue(maxsize=10)

    await enqueue_incoming_events(pubsub, queue, Debouncer())

    assert queue.qsize() == 0


@pytest.mark.asyncio
async def test_send_queued_notifications_sends_via_telegram_client(monkeypatch):
    import notifications.main as main_module

    monkeypatch.setitem(main_module.CHAT_ID_BY_CHANNEL, Channel.ALERTS, "chat-123")

    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(RoutedNotification(Channel.ALERTS, "🛑 Test", True, "k", False))

    telegram_client = AsyncMock()

    async def stop_after_one():
        await send_queued_notifications(queue, telegram_client)

    task = asyncio.create_task(stop_after_one())
    await asyncio.sleep(0.05)
    task.cancel()

    telegram_client.send_message.assert_awaited_once_with("chat-123", "🛑 Test", disable_notification=False)


@pytest.mark.asyncio
async def test_send_queued_notifications_skips_channel_without_configured_chat_id(monkeypatch):
    import notifications.main as main_module

    monkeypatch.setitem(main_module.CHAT_ID_BY_CHANNEL, Channel.PAPER, "")

    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(RoutedNotification(Channel.PAPER, "trade simulé", False, "k", False))

    telegram_client = AsyncMock()

    task = asyncio.create_task(send_queued_notifications(queue, telegram_client))
    await asyncio.sleep(0.05)
    task.cancel()

    telegram_client.send_message.assert_not_awaited()
