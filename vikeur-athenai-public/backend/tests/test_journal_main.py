"""Tests de journal.main (correctif du 16/08/2026 - persistance manquante
de events_journal, découverte en construisant "Why No Trade")."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from journal.main import consume_and_persist, parse_journal_message, persist_event


def test_parse_journal_message_returns_none_on_invalid_json():
    assert parse_journal_message(b"not-json{{{") is None


def test_parse_journal_message_parses_valid_payload():
    raw = json.dumps(
        {"source_module": "api", "event_type": "kill_switch.activated", "payload": {"active": True}}
    )
    assert parse_journal_message(raw) == {
        "source_module": "api",
        "event_type": "kill_switch.activated",
        "payload": {"active": True},
    }


def _make_pool():
    conn = AsyncMock()
    conn.execute = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


@pytest.mark.asyncio
async def test_persist_event_inserts_the_expected_row():
    pool, conn = _make_pool()

    result = await persist_event(
        pool,
        {
            "source_module": "decision_engine",
            "event_type": "decision_engine.no_opinion",
            "payload": {"symbol": "BTC/USDT"},
        },
    )

    assert result is True
    call = conn.execute.call_args
    assert "INSERT INTO events_journal" in call.args[0]
    assert call.args[1] == "decision_engine"
    assert call.args[2] == "decision_engine.no_opinion"


@pytest.mark.asyncio
async def test_persist_event_skips_incomplete_event_without_writing():
    pool, conn = _make_pool()

    result = await persist_event(pool, {"payload": {}})  # source_module/event_type absents

    assert result is False
    conn.execute.assert_not_called()


class _FakePubSub:
    def __init__(self, raw_messages: list[bytes]):
        self._raw_messages = raw_messages

    async def listen(self):
        for raw in self._raw_messages:
            yield {"type": "message", "data": raw}


def _event(event_type: str, source_module: str = "decision_engine", payload: dict | None = None) -> bytes:
    return json.dumps(
        {"source_module": source_module, "event_type": event_type, "payload": payload or {}}
    ).encode()


@pytest.mark.asyncio
async def test_consume_and_persist_writes_every_valid_message():
    pool, conn = _make_pool()
    pubsub = _FakePubSub(
        [_event("decision_engine.no_opinion"), _event("decision_engine.engine_skipped_regime")]
    )

    await consume_and_persist(pubsub, pool)

    assert conn.execute.await_count == 2


@pytest.mark.asyncio
async def test_consume_and_persist_ignores_non_message_types():
    pool, conn = _make_pool()

    async def fake_listen():
        yield {"type": "subscribe", "data": 1}

    pubsub = _FakePubSub([])
    pubsub.listen = fake_listen

    await consume_and_persist(pubsub, pool)

    conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_consume_and_persist_continues_after_a_write_failure():
    """Une panne DB sur un événement ne doit jamais arrêter le
    traitement des événements suivants."""
    pool, conn = _make_pool()
    conn.execute = AsyncMock(side_effect=[RuntimeError("panne DB"), None])
    pubsub = _FakePubSub([_event("a.error"), _event("b.error")])

    await consume_and_persist(pubsub, pool)  # ne doit pas lever

    assert conn.execute.await_count == 2
