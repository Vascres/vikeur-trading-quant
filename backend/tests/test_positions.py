"""Tests de execution_engine/positions.py (Phase 15, §5).

Utilise des mocks asyncpg pour vérifier la logique d'ouverture/fermeture
sans dépendre d'une vraie base de données (module purement orchestré
par des appels SQL simples, mockables proprement).
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from execution_engine.positions import FuturesFillResult, apply_fill, record_conditional_order_ids


def _make_pool(fetchrow_result=None, fetchval_result=1):
    conn = AsyncMock()
    conn.fetchrow.return_value = fetchrow_result
    conn.fetchval.return_value = fetchval_result
    conn.execute = AsyncMock()

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


@pytest.mark.asyncio
async def test_buy_without_existing_position_inserts_new_row():
    pool, conn = _make_pool(fetchrow_result=None)

    await apply_fill(
        pool,
        exchange="htx",
        symbol="BTC/USDT",
        execution_mode="paper",
        side="buy",
        filled_price=Decimal("60000"),
        filled_quantity=Decimal("0.01"),
    )

    insert_call = conn.execute.call_args
    assert "INSERT INTO positions" in insert_call.args[0]


@pytest.mark.asyncio
async def test_buy_with_existing_position_updates_weighted_average():
    existing = {"id": 1, "entry_price": Decimal("60000"), "quantity": Decimal("0.01")}
    pool, conn = _make_pool(fetchrow_result=existing)

    await apply_fill(
        pool,
        exchange="htx",
        symbol="BTC/USDT",
        execution_mode="paper",
        side="buy",
        filled_price=Decimal("62000"),
        filled_quantity=Decimal("0.01"),
    )

    update_call = conn.execute.call_args
    assert "UPDATE positions SET entry_price" in update_call.args[0]
    weighted_price, total_quantity, position_id = (
        update_call.args[1],
        update_call.args[2],
        update_call.args[3],
    )
    assert weighted_price == Decimal("61000")
    assert total_quantity == Decimal("0.02")
    assert position_id == 1


@pytest.mark.asyncio
async def test_sell_with_existing_position_closes_it_fully():
    existing = {"id": 42, "entry_price": Decimal("60000"), "quantity": Decimal("0.05")}
    pool, conn = _make_pool(fetchrow_result=existing)

    await apply_fill(
        pool,
        exchange="htx",
        symbol="BTC/USDT",
        execution_mode="paper",
        side="sell",
        filled_price=Decimal("61000"),
        filled_quantity=Decimal("0.01"),  # ignoré : Phase 15 §3, la vente clôture tout
    )

    update_call = conn.execute.call_args
    assert "status = 'closed'" in update_call.args[0]
    filled_price, realized_pnl = update_call.args[1], update_call.args[2]
    assert filled_price == Decimal("61000")
    assert realized_pnl == Decimal("50")  # (61000-60000)*0.05


@pytest.mark.asyncio
async def test_sell_without_existing_position_is_noop_and_journaled():
    pool, conn = _make_pool(fetchrow_result=None)
    journal_events = []

    await apply_fill(
        pool,
        exchange="htx",
        symbol="BTC/USDT",
        execution_mode="paper",
        side="sell",
        filled_price=Decimal("61000"),
        filled_quantity=Decimal("0.01"),
        publish_journal_event=lambda t, p: journal_events.append((t, p)),
    )

    conn.execute.assert_not_called()
    assert any(e[0] == "execution_engine.sell_without_position" for e in journal_events)


# --- ADR-0019 : futures (market_type='futures_perpetual') ---


@pytest.mark.asyncio
async def test_futures_sell_without_existing_position_opens_a_short():
    """Contrairement au spot, une vente futures sans position existante
    ouvre légitimement une position courte - jamais un no-op (ADR-0019)."""
    pool, conn = _make_pool(fetchrow_result=None, fetchval_result=101)

    result = await apply_fill(
        pool,
        exchange="htx",
        symbol="BTC/USDT",
        execution_mode="paper",
        side="sell",
        filled_price=Decimal("60000"),
        filled_quantity=Decimal("0.01"),
        market_type="futures_perpetual",
    )

    insert_call = conn.fetchval.call_args
    assert "INSERT INTO positions" in insert_call.args[0]
    assert "short" in insert_call.args
    assert result == FuturesFillResult(position_id=101, opened=True, closed=False)


@pytest.mark.asyncio
async def test_futures_buy_without_existing_position_opens_a_long():
    pool, conn = _make_pool(fetchrow_result=None, fetchval_result=102)

    result = await apply_fill(
        pool,
        exchange="htx",
        symbol="BTC/USDT",
        execution_mode="paper",
        side="buy",
        filled_price=Decimal("60000"),
        filled_quantity=Decimal("0.01"),
        market_type="futures_perpetual",
    )

    insert_call = conn.fetchval.call_args
    assert "long" in insert_call.args
    assert result.opened is True


@pytest.mark.asyncio
async def test_futures_entry_persists_leverage_margin_and_liquidation_reference():
    """Étapes 7-8 (16/08/2026) : ces trois valeurs, calculées par
    l'appelant (`execution_engine/modes/real.py`), doivent être
    transmises jusqu'à l'INSERT - jamais recalculées ici."""
    pool, conn = _make_pool(fetchrow_result=None, fetchval_result=103)

    await apply_fill(
        pool,
        exchange="htx",
        symbol="ETH/USDT",
        execution_mode="real",
        side="buy",
        filled_price=Decimal("3000"),
        filled_quantity=Decimal("0.05"),
        market_type="futures_perpetual",
        leverage=1,
        margin_used=Decimal("150"),
        liquidation_price_reference=Decimal("1512"),
    )

    insert_call = conn.fetchval.call_args
    assert insert_call.args[9] == 1
    assert insert_call.args[10] == Decimal("150")
    assert insert_call.args[11] == Decimal("1512")


@pytest.mark.asyncio
async def test_futures_same_side_fill_averages_into_existing_position():
    existing = {
        "id": 7,
        "entry_price": Decimal("60000"),
        "quantity": Decimal("0.01"),
        "position_side": "short",
        "stop_loss_order_id": "stop-1",
        "take_profit_order_id": None,
    }
    pool, conn = _make_pool(fetchrow_result=existing)

    result = await apply_fill(
        pool,
        exchange="htx",
        symbol="BTC/USDT",
        execution_mode="paper",
        side="sell",  # renforce le short existant
        filled_price=Decimal("62000"),
        filled_quantity=Decimal("0.01"),
        market_type="futures_perpetual",
    )

    update_call = conn.execute.call_args
    assert "UPDATE positions SET entry_price" in update_call.args[0]
    assert update_call.args[1] == Decimal("61000")  # moyenne pondérée
    assert update_call.args[2] == Decimal("0.02")
    assert result == FuturesFillResult(position_id=7, opened=False, closed=False)


@pytest.mark.asyncio
async def test_futures_opposite_side_fill_closes_short_position_with_correct_pnl():
    """Une position courte gagne quand le prix baisse - inverse du spot/long."""
    existing = {
        "id": 9,
        "entry_price": Decimal("60000"),
        "quantity": Decimal("0.01"),
        "position_side": "short",
        "stop_loss_order_id": "stop-9",
        "take_profit_order_id": "tp-9",
    }
    pool, conn = _make_pool(fetchrow_result=existing)

    result = await apply_fill(
        pool,
        exchange="htx",
        symbol="BTC/USDT",
        execution_mode="paper",
        side="buy",  # rachat -> clôture du short
        filled_price=Decimal("58000"),
        filled_quantity=Decimal("0.01"),
        market_type="futures_perpetual",
    )

    update_call = conn.execute.call_args
    assert "status = 'closed'" in update_call.args[0]
    filled_price, realized_pnl = update_call.args[1], update_call.args[2]
    assert filled_price == Decimal("58000")
    assert realized_pnl == Decimal("20")  # (60000-58000)*0.01, profit sur un short en baisse
    assert result == FuturesFillResult(
        position_id=9,
        opened=False,
        closed=True,
        previous_stop_loss_order_id="stop-9",
        previous_take_profit_order_id="tp-9",
    )


@pytest.mark.asyncio
async def test_futures_opposite_side_fill_closes_long_position_with_correct_pnl():
    existing = {
        "id": 10,
        "entry_price": Decimal("60000"),
        "quantity": Decimal("0.01"),
        "position_side": "long",
        "stop_loss_order_id": None,
        "take_profit_order_id": None,
    }
    pool, conn = _make_pool(fetchrow_result=existing)

    await apply_fill(
        pool,
        exchange="htx",
        symbol="BTC/USDT",
        execution_mode="paper",
        side="sell",
        filled_price=Decimal("61000"),
        filled_quantity=Decimal("0.01"),
        market_type="futures_perpetual",
    )

    update_call = conn.execute.call_args
    realized_pnl = update_call.args[2]
    assert realized_pnl == Decimal("10")  # (61000-60000)*0.01, profit sur un long en hausse


@pytest.mark.asyncio
async def test_spot_and_futures_positions_never_mixed_in_the_lookup_query():
    """La requête d'existence doit filtrer par market_type (ADR-0019 §2) -
    vérifie que la clause SQL le fait, pas seulement le comportement."""
    pool, conn = _make_pool(fetchrow_result=None)

    await apply_fill(
        pool,
        exchange="htx",
        symbol="BTC/USDT",
        execution_mode="paper",
        side="buy",
        filled_price=Decimal("60000"),
        filled_quantity=Decimal("0.01"),
        market_type="spot",
    )

    select_call = conn.fetchrow.call_args
    assert "market_type = 'spot'" in select_call.args[0]


@pytest.mark.asyncio
async def test_spot_fill_returns_none_not_a_futures_result():
    """`FuturesFillResult` n'est jamais retourné pour le spot -
    comportement inchangé pour tout appelant existant (Étape 9, 16/08/2026)."""
    pool, conn = _make_pool(fetchrow_result=None)

    result = await apply_fill(
        pool,
        exchange="htx",
        symbol="BTC/USDT",
        execution_mode="paper",
        side="buy",
        filled_price=Decimal("60000"),
        filled_quantity=Decimal("0.01"),
        market_type="spot",
    )

    assert result is None


# --- Étape 9 (16/08/2026) : record_conditional_order_ids ---


@pytest.mark.asyncio
async def test_record_conditional_order_ids_writes_stop_loss_only():
    pool, conn = _make_pool()

    await record_conditional_order_ids(pool, 42, stop_loss_order_id="stop-42")

    call = conn.execute.call_args
    assert call.args[1] == "stop-42"
    assert call.args[2] is None
    assert call.args[3] == 42
