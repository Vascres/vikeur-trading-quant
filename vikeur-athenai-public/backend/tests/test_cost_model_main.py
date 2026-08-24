"""Tests de cost_model.main.run_cost_model_cycle (ADR-0016, étendu ADR-0020,
étendu multi-exchange par le chantier CostModel unique du 16/08/2026).

Isole la logique d'orchestration (persistance en base, événements
journalisés) des appels réseau réels via des adaptateurs factices -
chaque fetcher (HTX, Binance) est déjà testé séparément dans
test_htx_fee_fetcher.py / test_binance_fee_fetcher.py / test_htx_funding_fetcher.py.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from cost_model.main import run_cost_model_cycle


def _make_pool():
    conn = AsyncMock()
    conn.execute = AsyncMock()

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


def _make_adapter(fee_rate_response: list[dict]):
    adapter = AsyncMock()
    adapter.get_fee_rate.return_value = fee_rate_response
    return adapter


def _make_futures_adapter(funding_rates: list):
    """`funding_rates` : une valeur (Decimal ou Exception) par symbole
    suivi, dans l'ordre BTC/ETH/SOL - appliqué comme `side_effect` sur
    des appels successifs à `get_funding_rate` (un par symbole, cf.
    ADR-0020, aucun appel groupé côté futures contrairement au spot)."""
    adapter = AsyncMock()
    adapter.get_funding_rate.side_effect = funding_rates
    return adapter


@pytest.mark.asyncio
async def test_persists_one_row_per_tracked_symbol_for_fees_and_funding():
    pool, conn = _make_pool()
    adapter = _make_adapter(
        [
            {"symbol": "btcusdt", "makerFeeRate": "0.002", "takerFeeRate": "0.002"},
            {"symbol": "ethusdt", "makerFeeRate": "0.002", "takerFeeRate": "0.002"},
            {"symbol": "solusdt", "makerFeeRate": "0.002", "takerFeeRate": "0.002"},
        ]
    )
    futures_adapter = _make_futures_adapter([Decimal("0.0001"), Decimal("0.0002"), Decimal("0.0003")])
    published = []

    await run_cost_model_cycle(pool, "htx", adapter, futures_adapter, lambda t, p: published.append((t, p)))

    # 3 UPSERT fee_schedule + 3 UPSERT funding_rates = 6 exécutions.
    assert conn.execute.await_count == 6
    assert published[0][0] == "cost_model.run_completed"
    assert published[0][1]["exchange"] == "htx"
    assert set(published[0][1]["symbols"]) == {"BTC/USDT", "ETH/USDT", "SOL/USDT"}
    assert set(published[0][1]["funding_rate_bps"]) == {"BTC/USDT", "ETH/USDT", "SOL/USDT"}


@pytest.mark.asyncio
async def test_falls_back_gracefully_when_htx_fee_api_call_fails():
    """Une panne de l'API de frais ne doit jamais faire planter le cycle -
    persiste un repli documenté et continue (le prochain cycle retentera)."""
    pool, conn = _make_pool()
    adapter = AsyncMock()
    adapter.get_fee_rate.side_effect = RuntimeError("HTX indisponible")
    futures_adapter = _make_futures_adapter([Decimal("0.0001"), Decimal("0.0002"), Decimal("0.0003")])
    published = []

    await run_cost_model_cycle(pool, "htx", adapter, futures_adapter, lambda t, p: published.append((t, p)))

    assert conn.execute.await_count == 6  # 3 replis fee_schedule + 3 mesures funding
    assert all(source == "documented_fallback" for source in published[0][1]["sources"].values())


@pytest.mark.asyncio
async def test_funding_failure_does_not_block_fee_measurement_nor_the_cycle():
    """ADR-0020 : contrairement aux frais, une panne de funding n'a pas de
    repli - le cycle continue quand même, avec les symboles en échec
    simplement absents de `funding_rate_bps`."""
    pool, conn = _make_pool()
    adapter = _make_adapter(
        [
            {"symbol": "btcusdt", "makerFeeRate": "0.002", "takerFeeRate": "0.002"},
            {"symbol": "ethusdt", "makerFeeRate": "0.002", "takerFeeRate": "0.002"},
            {"symbol": "solusdt", "makerFeeRate": "0.002", "takerFeeRate": "0.002"},
        ]
    )
    futures_adapter = _make_futures_adapter(
        [RuntimeError("panne funding"), Decimal("0.0002"), Decimal("0.0003")]
    )
    published = []

    await run_cost_model_cycle(pool, "htx", adapter, futures_adapter, lambda t, p: published.append((t, p)))

    assert conn.execute.await_count == 5  # 3 fee_schedule + 2 funding_rates (BTC en échec, omis)
    assert set(published[0][1]["funding_rate_bps"]) == {"ETH/USDT", "SOL/USDT"}


# --- Chantier CostModel unique (16/08/2026) : dispatch multi-exchange ---


@pytest.mark.asyncio
async def test_binance_cycle_persists_fees_but_no_funding_without_futures_adapter():
    """Binance n'a pas encore d'adaptateur futures (Étapes 7-8 à venir) -
    le cycle doit fonctionner sans lui (funding_adapter=None), et ne
    doit tenter aucune mesure de funding."""
    pool, conn = _make_pool()
    adapter = _make_adapter(
        [
            {"symbol": "BTCUSDT", "makerCommission": "0.001", "takerCommission": "0.001"},
            {"symbol": "ETHUSDT", "makerCommission": "0.001", "takerCommission": "0.001"},
            {"symbol": "SOLUSDT", "makerCommission": "0.001", "takerCommission": "0.001"},
        ]
    )
    published = []

    await run_cost_model_cycle(pool, "binance", adapter, None, lambda t, p: published.append((t, p)))

    assert conn.execute.await_count == 3  # 3 UPSERT fee_schedule seulement, aucun funding
    assert published[0][1]["exchange"] == "binance"
    assert published[0][1]["funding_rate_bps"] == {}


@pytest.mark.asyncio
async def test_binance_fee_source_labelled_correctly_on_measured_success():
    pool, conn = _make_pool()
    adapter = _make_adapter([{"symbol": "BTCUSDT", "makerCommission": "0.001", "takerCommission": "0.001"}])
    published = []

    await run_cost_model_cycle(pool, "binance", adapter, None, lambda t, p: published.append((t, p)))

    assert published[0][1]["sources"]["BTC/USDT"] == "measured_api"


@pytest.mark.asyncio
async def test_binance_cycle_measures_funding_when_futures_adapter_provided():
    """Étapes 7-8 (16/08/2026) : contrairement au test ci-dessus (aucun
    adaptateur futures), Binance mesure désormais aussi le funding quand
    un `BinanceFuturesAdapter` est fourni - même chemin que HTX."""
    pool, conn = _make_pool()
    adapter = _make_adapter([{"symbol": "BTCUSDT", "makerCommission": "0.001", "takerCommission": "0.001"}])
    futures_adapter = _make_futures_adapter([Decimal("0.0001"), Decimal("0.0002"), Decimal("0.0003")])
    published = []

    await run_cost_model_cycle(
        pool, "binance", adapter, futures_adapter, lambda t, p: published.append((t, p))
    )

    assert published[0][1]["funding_rate_bps"]["BTC/USDT"] == pytest.approx(1.0)
    assert set(published[0][1]["funding_rate_bps"]) == {"BTC/USDT", "ETH/USDT", "SOL/USDT"}
