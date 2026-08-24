"""Tests de cost_model.binance_fee_fetcher (chantier CostModel unique, 16/08/2026)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from cost_model.binance_fee_fetcher import fetch_binance_fee_schedule
from cost_model.fee_schedule import DOCUMENTED_FALLBACK, MEASURED_API


@pytest.mark.asyncio
async def test_uses_the_effective_account_rate_directly():
    """Contrairement à HTX, Binance renvoie déjà le taux net de toute
    remise - pas de distinction taux de base/taux réel à faire ici."""
    adapter = AsyncMock()
    adapter.get_fee_rate.return_value = [
        {"symbol": "BTCUSDT", "makerCommission": "0.00075", "takerCommission": "0.001"}
    ]

    schedules = await fetch_binance_fee_schedule(adapter, ["BTC/USDT"])

    assert len(schedules) == 1
    assert schedules[0].source == MEASURED_API
    assert schedules[0].maker_fee_bps == pytest.approx(7.5)
    assert schedules[0].taker_fee_bps == pytest.approx(10.0)


@pytest.mark.asyncio
async def test_falls_back_to_documented_schedule_when_api_call_fails():
    adapter = AsyncMock()
    adapter.get_fee_rate.side_effect = RuntimeError("Binance indisponible")

    schedules = await fetch_binance_fee_schedule(adapter, ["BTC/USDT", "SOL/USDT"])

    assert len(schedules) == 2
    assert all(s.source == DOCUMENTED_FALLBACK for s in schedules)
    assert all(s.taker_fee_bps == 10.0 for s in schedules)  # tarif de base Binance, pas HTX


@pytest.mark.asyncio
async def test_falls_back_per_symbol_when_binance_omits_one_symbol_from_response():
    adapter = AsyncMock()
    adapter.get_fee_rate.return_value = [
        {"symbol": "BTCUSDT", "makerCommission": "0.001", "takerCommission": "0.001"}
    ]  # SOLUSDT absent de la réponse

    schedules = await fetch_binance_fee_schedule(adapter, ["BTC/USDT", "SOL/USDT"])

    by_symbol = {s.symbol: s for s in schedules}
    assert by_symbol["BTC/USDT"].source == MEASURED_API
    assert by_symbol["SOL/USDT"].source == DOCUMENTED_FALLBACK


@pytest.mark.asyncio
async def test_converts_canonical_symbols_to_uppercase_native_before_calling_adapter():
    adapter = AsyncMock()
    adapter.get_fee_rate.return_value = []

    await fetch_binance_fee_schedule(adapter, ["BTC/USDT"])

    called_with = adapter.get_fee_rate.call_args.args[0]
    assert called_with == ["BTCUSDT"]
