"""Tests de liquidation_ingest.main (chantier de données Liquidation
Cascade, 16/08/2026)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from data_collector.adapters.binance_futures import LiquidationEvent
from liquidation_ingest.main import consume_liquidations, persist_liquidation_event


def _make_pool():
    conn = AsyncMock()
    conn.execute = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


def _event(**overrides) -> LiquidationEvent:
    defaults = dict(
        exchange="binance",
        symbol="BTC/USDT",
        side="sell",
        price=Decimal("60000"),
        quantity=Decimal("0.01"),
        notional=Decimal("600"),
        order_status="FILLED",
        event_time=datetime.now(tz=UTC),
    )
    defaults.update(overrides)
    return LiquidationEvent(**defaults)


@pytest.mark.asyncio
async def test_persist_liquidation_event_inserts_the_expected_row():
    pool, conn = _make_pool()

    await persist_liquidation_event(pool, _event())

    call = conn.execute.call_args
    assert "INSERT INTO liquidation_events" in call.args[0]
    assert call.args[1] == "binance"
    assert call.args[2] == "BTC/USDT"
    assert call.args[3] == "sell"


@pytest.mark.asyncio
async def test_consume_liquidations_parses_and_persists_each_message():
    pool, conn = _make_pool()
    adapter = AsyncMock()

    async def fake_stream(symbols):
        yield (
            '{"e":"forceOrder","E":1568014460893,"o":{"s":"BTCUSDT","S":"SELL","o":"LIMIT",'
            '"f":"IOC","q":"0.014","p":"9910","ap":"9910","X":"FILLED","l":"0.014","z":"0.014",'
            '"T":1568014460893}}'
        )
        yield (
            '{"e":"forceOrder","E":1568014460893,"o":{"s":"ETHUSDT","S":"BUY","o":"LIMIT",'
            '"f":"IOC","q":"1.0","p":"3000","ap":"3000","X":"FILLED","l":"1.0","z":"1.0",'
            '"T":1568014460893}}'
        )

    adapter.stream_liquidations = fake_stream

    await consume_liquidations(adapter, pool, ["btcusdt", "ethusdt"])

    assert conn.execute.await_count == 2


@pytest.mark.asyncio
async def test_consume_liquidations_skips_unparseable_messages_without_writing():
    pool, conn = _make_pool()
    adapter = AsyncMock()

    async def fake_stream(symbols):
        yield "not-json{{{"

    adapter.stream_liquidations = fake_stream

    await consume_liquidations(adapter, pool, ["btcusdt"])

    conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_consume_liquidations_continues_after_a_persistence_failure():
    pool, conn = _make_pool()
    conn.execute = AsyncMock(side_effect=[RuntimeError("panne DB"), None])
    adapter = AsyncMock()

    valid_message = (
        '{"e":"forceOrder","E":1568014460893,"o":{"s":"BTCUSDT","S":"SELL","o":"LIMIT",'
        '"f":"IOC","q":"0.014","p":"9910","ap":"9910","X":"FILLED","l":"0.014","z":"0.014",'
        '"T":1568014460893}}'
    )

    async def fake_stream(symbols):
        yield valid_message
        yield valid_message

    adapter.stream_liquidations = fake_stream

    await consume_liquidations(adapter, pool, ["btcusdt"])  # ne doit pas lever

    assert conn.execute.await_count == 2
