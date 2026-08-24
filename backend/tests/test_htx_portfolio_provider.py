"""Tests de portfolio.htx_provider.HTXPortfolioProvider (ADR-0007).

Réutilise HTXAdapter.get_balances() (déjà couvert par ses propres tests
d'authentification/signature) - ces tests portent uniquement sur la
valorisation en devise de référence, la responsabilité propre de ce
module.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from portfolio.htx_provider import HTXPortfolioProvider


def _make_pool(price_by_symbol: dict[str, Decimal]):
    async def fetchrow_side_effect(query, exchange, symbol):
        price = price_by_symbol.get(symbol)
        return {"close": price} if price is not None else None

    conn = AsyncMock()
    conn.fetchrow.side_effect = fetchrow_side_effect

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


def _make_adapter(balances: dict[str, Decimal]):
    adapter = MagicMock()
    adapter.get_balances = AsyncMock(return_value=balances)
    return adapter


@pytest.mark.asyncio
async def test_take_snapshot_sums_reference_currency_directly():
    adapter = _make_adapter({"USDT": Decimal("500")})
    pool = _make_pool({})
    provider = HTXPortfolioProvider(adapter, pool)

    snapshot = await provider.take_snapshot()

    assert snapshot.total_value_reference_currency == Decimal("500")
    assert snapshot.reference_currency == "USDT"
    assert snapshot.balances == {"USDT": Decimal("500")}


@pytest.mark.asyncio
async def test_take_snapshot_converts_other_assets_using_latest_price():
    adapter = _make_adapter({"USDT": Decimal("500"), "BTC": Decimal("0.1")})
    pool = _make_pool({"BTC/USDT": Decimal("60000")})
    provider = HTXPortfolioProvider(adapter, pool)

    snapshot = await provider.take_snapshot()

    # 500 USDT + 0.1 BTC * 60000 = 6500
    assert snapshot.total_value_reference_currency == Decimal("6500")


@pytest.mark.asyncio
async def test_take_snapshot_excludes_untracked_asset_from_total_but_keeps_it_visible():
    adapter = _make_adapter({"USDT": Decimal("500"), "SOME_UNTRACKED_TOKEN": Decimal("10")})
    pool = _make_pool({})  # aucun prix suivi pour SOME_UNTRACKED_TOKEN/USDT
    provider = HTXPortfolioProvider(adapter, pool)

    snapshot = await provider.take_snapshot()

    assert snapshot.total_value_reference_currency == Decimal("500")  # jeton exclu du total
    assert snapshot.balances["SOME_UNTRACKED_TOKEN"] == Decimal("10")  # mais toujours visible


@pytest.mark.asyncio
async def test_take_snapshot_ignores_zero_balances():
    adapter = _make_adapter({"USDT": Decimal("500"), "ETH": Decimal("0")})
    pool = _make_pool({})
    provider = HTXPortfolioProvider(adapter, pool)

    snapshot = await provider.take_snapshot()

    assert snapshot.total_value_reference_currency == Decimal("500")
