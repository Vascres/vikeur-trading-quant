"""Tests de portfolio.main.take_and_check_snapshot (ADR-0003, ADR-0007).

Vérifie la persistance de l'instantané et la détection de divergence de
réconciliation (événement ReconciliationDiscrepancyDetected, Event
Architecture Spec §3) - jamais silencieuse au-delà de la tolérance
configurée.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from portfolio.main import RECONCILIATION_TOLERANCE, take_and_check_snapshot
from shared.portfolio_provider import PortfolioSnapshot


def _make_pool(
    previous_snapshot: dict | None, realized_pnl_total: Decimal = Decimal("0"), current_mode: str = "paper"
):
    async def fetchrow_side_effect(query, *args):
        if "ORDER BY taken_at DESC LIMIT 1" in query:
            return previous_snapshot
        if "execution_mode_state" in query:
            return {"mode": current_mode}
        if "closed_at >" in query:
            # Correctif du 17/08/2026 (solde de marge futures) : ne
            # dépend plus du numéro exact du placeholder ("$2" a glissé à
            # "$3" quand `market_type` a été ajouté à cette requête) -
            # matcher sur "closed_at >" seul, robuste à un futur
            # paramètre supplémentaire.
            return {"total": realized_pnl_total}
        raise AssertionError(f"Requête fetchrow non attendue : {query}")

    conn = AsyncMock()
    conn.fetchrow.side_effect = fetchrow_side_effect
    conn.fetchval = AsyncMock(return_value=1)
    conn.execute = AsyncMock()

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


def _make_provider(total: Decimal, balances: dict[str, Decimal] | None = None):
    provider = MagicMock()
    provider.exchange_name = "htx"
    provider.take_snapshot = AsyncMock(
        return_value=PortfolioSnapshot(
            exchange="htx",
            taken_at=datetime.now(tz=UTC),
            reference_currency="USDT",
            total_value_reference_currency=total,
            balances=balances or {"USDT": total},
        )
    )
    return provider


@pytest.mark.asyncio
async def test_first_snapshot_ever_is_persisted_without_reconciliation_check():
    pool, conn = _make_pool(previous_snapshot=None)
    provider = _make_provider(Decimal("1000"))
    published = []

    await take_and_check_snapshot(pool, provider, lambda t, p: published.append((t, p)))

    conn.execute.assert_called()  # insertion des soldes par actif
    assert any(t == "portfolio_aggregator.snapshot_taken" for t, _ in published)
    assert not any(t == "portfolio_aggregator.reconciliation_discrepancy_detected" for t, _ in published)


@pytest.mark.asyncio
async def test_no_discrepancy_when_delta_within_tolerance():
    previous = {"id": 1, "taken_at": datetime.now(tz=UTC), "total_value_reference_currency": Decimal("1000")}
    pool, _ = _make_pool(previous_snapshot=previous, realized_pnl_total=Decimal("5"))
    # attendu = 1000 + 5 = 1005 ; observé = 1005 -> aucun écart
    provider = _make_provider(Decimal("1005"))
    published = []

    await take_and_check_snapshot(pool, provider, lambda t, p: published.append((t, p)))

    assert not any(t == "portfolio_aggregator.reconciliation_discrepancy_detected" for t, _ in published)


@pytest.mark.asyncio
async def test_discrepancy_detected_beyond_tolerance():
    previous = {"id": 1, "taken_at": datetime.now(tz=UTC), "total_value_reference_currency": Decimal("1000")}
    pool, _ = _make_pool(previous_snapshot=previous, realized_pnl_total=Decimal("0"))
    # attendu = 1000 ; observé = 1000 + 2x la tolérance -> écart détecté
    observed = Decimal("1000") + (RECONCILIATION_TOLERANCE * 2)
    provider = _make_provider(observed)
    published = []

    await take_and_check_snapshot(pool, provider, lambda t, p: published.append((t, p)))

    discrepancy_events = [
        p for t, p in published if t == "portfolio_aggregator.reconciliation_discrepancy_detected"
    ]
    assert len(discrepancy_events) == 1
    assert discrepancy_events[0]["exchange"] == "htx"


# --- Solde de marge futures (17/08/2026) ---


@pytest.mark.asyncio
async def test_futures_snapshot_persists_and_reconciles_with_explicit_market_type():
    """`is_futures=True` doit se traduire par market_type='futures_perpetual'
    à l'insertion ET dans la requête de réconciliation - jamais confondu
    avec le P&L spot (positions.market_type='spot')."""
    previous = {"id": 1, "taken_at": datetime.now(tz=UTC), "total_value_reference_currency": Decimal("50")}
    pool, conn = _make_pool(previous_snapshot=previous, realized_pnl_total=Decimal("0"))
    provider = _make_provider(Decimal("50"))

    await take_and_check_snapshot(pool, provider, lambda t, p: None, is_futures=True)

    insert_call = conn.fetchval.call_args
    assert insert_call.args[5] == "futures_perpetual"  # market_type inséré explicitement

    # La requête de réconciliation doit avoir été appelée avec
    # market_type='futures_perpetual', jamais 'spot'.
    reconciliation_call = [c for c in conn.fetchrow.call_args_list if "realized_pnl" in c.args[0]][0]
    assert reconciliation_call.args[2] == "futures_perpetual"
