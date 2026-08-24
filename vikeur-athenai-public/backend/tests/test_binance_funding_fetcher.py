"""Tests de cost_model.binance_funding_fetcher (Étapes 7-8, 16/08/2026)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from cost_model.binance_funding_fetcher import fetch_binance_funding_rates
from cost_model.fee_schedule import MEASURED_API


@pytest.mark.asyncio
async def test_fetch_binance_funding_rates_converts_fraction_to_bps():
    adapter = AsyncMock()
    adapter.get_funding_rate.return_value = Decimal("0.0001")  # 0,01% -> 1 bps

    rates = await fetch_binance_funding_rates(adapter, ["BTC/USDT"])

    assert len(rates) == 1
    assert rates[0].exchange == "binance"
    assert rates[0].symbol == "BTC/USDT"
    assert rates[0].funding_rate_bps == pytest.approx(1.0)
    assert rates[0].source == MEASURED_API


@pytest.mark.asyncio
async def test_fetch_binance_funding_rates_omits_failing_symbol_without_fallback():
    """ADR-0020 : aucun repli inventé pour le funding - un échec par
    symbole est simplement omis, ne bloque pas les autres."""
    adapter = AsyncMock()
    adapter.get_funding_rate.side_effect = [RuntimeError("panne"), Decimal("0.0002")]

    rates = await fetch_binance_funding_rates(adapter, ["BTC/USDT", "ETH/USDT"])

    assert len(rates) == 1
    assert rates[0].symbol == "ETH/USDT"
