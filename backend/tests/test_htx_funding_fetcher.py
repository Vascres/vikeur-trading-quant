"""Tests de cost_model.htx_funding_fetcher (ADR-0020)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from cost_model.funding_rate import MEASURED_API
from cost_model.htx_funding_fetcher import fetch_htx_funding_rates


@pytest.mark.asyncio
async def test_measures_funding_for_every_symbol():
    adapter = AsyncMock()
    adapter.get_funding_rate.side_effect = [Decimal("0.0001"), Decimal("-0.0002"), Decimal("0.0")]

    rates = await fetch_htx_funding_rates(adapter, ["BTC/USDT", "ETH/USDT", "SOL/USDT"])

    assert len(rates) == 3
    assert all(r.source == MEASURED_API for r in rates)
    by_symbol = {r.symbol: r.funding_rate_bps for r in rates}
    assert by_symbol["BTC/USDT"] == pytest.approx(1.0)
    assert by_symbol["ETH/USDT"] == pytest.approx(-2.0)
    assert by_symbol["SOL/USDT"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_omits_symbol_on_failure_without_inventing_a_value():
    """ADR-0020 : contrairement aux frais (ADR-0016), aucun repli
    documenté n'a de sens pour le funding - un échec de mesure omet
    simplement le symbole, jamais une valeur inventée."""
    adapter = AsyncMock()
    adapter.get_funding_rate.side_effect = [Decimal("0.0001"), RuntimeError("panne HTX")]

    rates = await fetch_htx_funding_rates(adapter, ["BTC/USDT", "ETH/USDT"])

    assert len(rates) == 1
    assert rates[0].symbol == "BTC/USDT"


@pytest.mark.asyncio
async def test_one_symbol_failure_does_not_block_the_others():
    adapter = AsyncMock()
    adapter.get_funding_rate.side_effect = [
        RuntimeError("panne sur le premier"),
        Decimal("0.0003"),
        Decimal("0.0004"),
    ]

    rates = await fetch_htx_funding_rates(adapter, ["BTC/USDT", "ETH/USDT", "SOL/USDT"])

    symbols = {r.symbol for r in rates}
    assert symbols == {"ETH/USDT", "SOL/USDT"}


@pytest.mark.asyncio
async def test_all_symbols_failing_returns_empty_list():
    adapter = AsyncMock()
    adapter.get_funding_rate.side_effect = RuntimeError("panne totale")

    rates = await fetch_htx_funding_rates(adapter, ["BTC/USDT", "ETH/USDT"])

    assert rates == []
