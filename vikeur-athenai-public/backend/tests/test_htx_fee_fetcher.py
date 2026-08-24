"""Tests de cost_model.htx_fee_fetcher (ADR-0016)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from cost_model.fee_schedule import DOCUMENTED_FALLBACK, MEASURED_API
from cost_model.htx_fee_fetcher import fetch_htx_fee_schedule


@pytest.mark.asyncio
async def test_prefers_actual_rate_over_base_rate_when_present():
    """Un compte avec une remise (VIP, jeton natif) doit être reflété par
    le taux réellement payé, pas le tarif affiché de base."""
    adapter = AsyncMock()
    adapter.get_fee_rate.return_value = [
        {
            "symbol": "btcusdt",
            "makerFeeRate": "0.002",
            "takerFeeRate": "0.002",
            "actualMakerRate": "0.0015",
            "actualTakerRate": "0.0015",
        }
    ]

    schedules = await fetch_htx_fee_schedule(adapter, ["BTC/USDT"])

    assert len(schedules) == 1
    assert schedules[0].source == MEASURED_API
    assert schedules[0].taker_fee_bps == pytest.approx(15.0)  # 0.15% -> 15 bps, pas 20


@pytest.mark.asyncio
async def test_falls_back_to_base_rate_when_actual_rate_absent():
    adapter = AsyncMock()
    adapter.get_fee_rate.return_value = [
        {"symbol": "ethusdt", "makerFeeRate": "0.002", "takerFeeRate": "0.002"}
    ]

    schedules = await fetch_htx_fee_schedule(adapter, ["ETH/USDT"])

    assert schedules[0].taker_fee_bps == pytest.approx(20.0)


@pytest.mark.asyncio
async def test_falls_back_to_documented_schedule_when_api_call_fails():
    adapter = AsyncMock()
    adapter.get_fee_rate.side_effect = RuntimeError("HTX indisponible")

    schedules = await fetch_htx_fee_schedule(adapter, ["BTC/USDT", "SOL/USDT"])

    assert len(schedules) == 2
    assert all(s.source == DOCUMENTED_FALLBACK for s in schedules)
    assert all(s.taker_fee_bps == 20.0 for s in schedules)


@pytest.mark.asyncio
async def test_falls_back_per_symbol_when_htx_omits_one_symbol_from_response():
    adapter = AsyncMock()
    adapter.get_fee_rate.return_value = [
        {"symbol": "btcusdt", "makerFeeRate": "0.002", "takerFeeRate": "0.002"}
    ]  # solusdt absent de la réponse

    schedules = await fetch_htx_fee_schedule(adapter, ["BTC/USDT", "SOL/USDT"])

    by_symbol = {s.symbol: s for s in schedules}
    assert by_symbol["BTC/USDT"].source == MEASURED_API
    assert by_symbol["SOL/USDT"].source == DOCUMENTED_FALLBACK
