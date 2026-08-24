"""Tests de strategy_lifecycle.repository (Étape 3 du plan validé le 16/08/2026)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from strategy_lifecycle.repository import (
    apply_transition,
    ensure_lifecycle_row,
    fetch_active_strategy_ids,
    fetch_all_lifecycle_statuses,
    fetch_lifecycle_status,
    fetch_recent_closed_trades,
    fetch_reference_capital,
    fetch_transitioned_at,
)


def _make_pool():
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])

    # `conn.transaction()` est un appel SYNCHRONE côté asyncpg réel, qui
    # retourne un gestionnaire de contexte asynchrone - contrairement au
    # reste de `conn` (AsyncMock), il doit rester un MagicMock ordinaire,
    # sinon l'appel lui-même devient une coroutine (bug de mock découvert
    # à l'exécution, pas un bug du code testé).
    transaction_cm = AsyncMock()
    transaction_cm.__aenter__ = AsyncMock(return_value=None)
    transaction_cm.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=transaction_cm)

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


@pytest.mark.asyncio
async def test_ensure_lifecycle_row_uses_on_conflict_do_nothing():
    pool, conn = _make_pool()
    await ensure_lifecycle_row(pool, strategy_id=1)
    conn.execute.assert_awaited_once()
    query = conn.execute.call_args.args[0]
    assert "ON CONFLICT (strategy_id) DO NOTHING" in query
    assert conn.execute.call_args.args[2] == "experimental"


@pytest.mark.asyncio
async def test_fetch_lifecycle_status_returns_none_when_absent():
    pool, conn = _make_pool()
    assert await fetch_lifecycle_status(pool, strategy_id=1) is None


@pytest.mark.asyncio
async def test_fetch_lifecycle_status_returns_the_status():
    pool, conn = _make_pool()
    conn.fetchrow = AsyncMock(return_value={"status": "under_review"})
    assert await fetch_lifecycle_status(pool, strategy_id=1) == "under_review"


@pytest.mark.asyncio
async def test_fetch_all_lifecycle_statuses_builds_a_dict_keyed_by_strategy_id():
    pool, conn = _make_pool()
    conn.fetch = AsyncMock(
        return_value=[{"strategy_id": 1, "status": "experimental"}, {"strategy_id": 2, "status": "degraded"}]
    )
    statuses = await fetch_all_lifecycle_statuses(pool)
    assert statuses == {1: "experimental", 2: "degraded"}


@pytest.mark.asyncio
async def test_fetch_transitioned_at_returns_none_when_absent():
    pool, conn = _make_pool()
    assert await fetch_transitioned_at(pool, strategy_id=1) is None


@pytest.mark.asyncio
async def test_fetch_reference_capital_returns_none_without_snapshot():
    pool, conn = _make_pool()
    assert await fetch_reference_capital(pool, exchange="htx") is None


@pytest.mark.asyncio
async def test_fetch_reference_capital_returns_the_latest_snapshot_value():
    pool, conn = _make_pool()
    conn.fetchrow = AsyncMock(return_value={"total_value_reference_currency": "350.00"})
    capital = await fetch_reference_capital(pool, exchange="htx")
    assert capital == Decimal("350.00")


@pytest.mark.asyncio
async def test_fetch_active_strategy_ids_returns_a_flat_list():
    pool, conn = _make_pool()
    conn.fetch = AsyncMock(return_value=[{"id": 1}, {"id": 2}, {"id": 3}])
    assert await fetch_active_strategy_ids(pool) == [1, 2, 3]


@pytest.mark.asyncio
async def test_fetch_recent_closed_trades_without_since_uses_two_positional_params():
    pool, conn = _make_pool()
    conn.fetch = AsyncMock(
        return_value=[
            {
                "realized_pnl": "1.50",
                "entry_price": "100.00",
                "quantity": "1.0",
                "closed_at": datetime.now(tz=UTC),
            }
        ]
    )
    trades = await fetch_recent_closed_trades(pool, strategy_id=1, limit=30)
    assert len(trades) == 1
    assert trades[0].realized_pnl == Decimal("1.50")
    assert trades[0].entry_notional == Decimal("100.00")
    query_params = conn.fetch.call_args.args[1:]
    assert query_params == (1, 30)


@pytest.mark.asyncio
async def test_fetch_recent_closed_trades_with_since_uses_three_positional_params():
    pool, conn = _make_pool()
    since = datetime(2026, 8, 1, tzinfo=UTC)
    await fetch_recent_closed_trades(pool, strategy_id=1, limit=50, since=since)
    query, *query_params = conn.fetch.call_args.args
    assert query_params == [1, 50, since]
    assert "closed_at > $3" in query


@pytest.mark.asyncio
async def test_apply_transition_writes_state_and_history_in_the_same_transaction():
    pool, conn = _make_pool()
    await apply_transition(
        pool,
        strategy_id=1,
        previous_status="experimental",
        new_status="under_review",
        reason="espérance nette négative",
        ev_net_bps=-5.0,
        cumulative_pnl=Decimal("-2.0"),
        profit_factor=0.9,
        sample_size=30,
    )
    conn.transaction.assert_called_once()
    assert conn.execute.await_count == 2
    state_call, history_call = conn.execute.call_args_list
    assert "strategy_lifecycle_state" in state_call.args[0]
    assert "strategy_lifecycle_history" in history_call.args[0]
    assert history_call.args[2] == "experimental"  # previous_status bien transmis à l'historique
    assert history_call.args[3] == "under_review"  # new_status
