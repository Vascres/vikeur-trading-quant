"""Tests de portfolio/generic_provider.py et portfolio/futures_provider.py.

Bug réel trouvé le 19/08/2026 (disque VPS à 98%, remonté jusqu'à
`portfolio_snapshot_balances` : 46,6 millions de lignes, 1361,7 par
relevé en moyenne) : `PortfolioSnapshot.balances` contenait TOUS les
actifs renvoyés par `get_balances()`/`get_account_balance()`, y compris
des centaines à solde nul - jamais filtré avant persistance. Le bug
remontait au 27/07 (premier relevé HTX), jamais détecté avant que
l'ajout de deux nouveaux fournisseurs (Binance spot, Binance futures,
16-17/08/2026) ne triple la vitesse d'accumulation et rende le problème
visible sur le disque.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from portfolio.futures_provider import FuturesPortfolioProvider
from portfolio.generic_provider import GenericPortfolioProvider


def _make_db_pool(price_by_symbol: dict[str, Decimal] | None = None):
    price_by_symbol = price_by_symbol or {}

    async def fetchrow_side_effect(query, exchange, symbol):
        close = price_by_symbol.get(symbol)
        return {"close": close} if close is not None else None

    conn = AsyncMock()
    conn.fetchrow.side_effect = fetchrow_side_effect
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


@pytest.mark.asyncio
async def test_generic_provider_never_persists_zero_balance_assets():
    """Le cœur du bug : sur ~1362 actifs typiquement renvoyés par un
    exchange, l'écrasante majorité sont à solde nul - aucun ne doit
    jamais apparaître dans `PortfolioSnapshot.balances`."""
    adapter = AsyncMock()
    adapter.get_balances.return_value = {
        "USDT": Decimal("1000"),
        "BTC": Decimal("0.01"),
        "XRP": Decimal("0"),
        "DOGE": Decimal("0"),
        "SHIB": Decimal("0"),
    }
    pool = _make_db_pool(price_by_symbol={"BTC/USDT": Decimal("65000")})
    provider = GenericPortfolioProvider("binance", adapter, pool)

    snapshot = await provider.take_snapshot()

    assert snapshot.balances == {"USDT": Decimal("1000"), "BTC": Decimal("0.01")}
    assert "XRP" not in snapshot.balances
    assert "DOGE" not in snapshot.balances
    assert "SHIB" not in snapshot.balances


@pytest.mark.asyncio
async def test_generic_provider_total_valuation_unaffected_by_the_fix():
    """Le filtrage ne doit jamais changer le total valorisé - seuls les
    actifs à solde nul (qui ne contribuaient déjà rien au total) sont
    retirés de `balances`."""
    adapter = AsyncMock()
    adapter.get_balances.return_value = {
        "USDT": Decimal("500"),
        "BTC": Decimal("0.01"),
        "ETH": Decimal("0"),
    }
    pool = _make_db_pool(price_by_symbol={"BTC/USDT": Decimal("65000")})
    provider = GenericPortfolioProvider("binance", adapter, pool)

    snapshot = await provider.take_snapshot()

    assert snapshot.total_value_reference_currency == Decimal("500") + Decimal("0.01") * Decimal("65000")


@pytest.mark.asyncio
async def test_futures_provider_never_persists_zero_balance_assets():
    adapter = AsyncMock()
    adapter.get_account_balance.return_value = {
        "USDT": Decimal("50"),
        "BNB": Decimal("0"),
        "BUSD": Decimal("0"),
    }
    provider = FuturesPortfolioProvider("binance", adapter, db_pool=MagicMock())

    snapshot = await provider.take_snapshot()

    assert snapshot.balances == {"USDT": Decimal("50")}
    assert snapshot.market_type == "futures_perpetual"


@pytest.mark.asyncio
async def test_futures_provider_total_uses_reference_currency_only():
    adapter = AsyncMock()
    adapter.get_account_balance.return_value = {"USDT": Decimal("50"), "BNB": Decimal("0.001")}
    provider = FuturesPortfolioProvider("binance", adapter, db_pool=MagicMock())

    snapshot = await provider.take_snapshot()

    assert snapshot.total_value_reference_currency == Decimal("50")
    assert snapshot.balances == {"USDT": Decimal("50"), "BNB": Decimal("0.001")}  # non-nul, donc conservé
