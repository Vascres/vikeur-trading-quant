"""Tests de RealExecutionMode pour le routage futures (ADR-0019).

Le plus important de ce chantier : vérifie que la porte de gouvernance
(`futures_real_trading_enabled`) est réellement appliquée, pas seulement
construite (ADR-0018 l'avait créée sans jamais l'appeler nulle part).
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from execution_engine.modes.real import RealExecutionMode
from shared.futures_adapter import PositionSide


def _db_pool_with_execute():
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchval = AsyncMock(return_value=1)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


@pytest.mark.asyncio
async def test_futures_order_refused_without_governance_attestation():
    """Le cœur du chantier : sans l'attestation explicite, aucun ordre
    futures réel n'est jamais placé, même si un adaptateur est configuré."""
    pool = _db_pool_with_execute()
    futures_adapter = AsyncMock()
    mode = RealExecutionMode(
        db_pool=pool, exchange_adapters={}, futures_exchange_adapters={"htx": futures_adapter}
    )

    with patch("execution_engine.modes.real.is_futures_real_trading_enabled", AsyncMock(return_value=False)):
        with pytest.raises(RuntimeError, match="futures_real_trading_enabled"):
            await mode.execute(
                risk_check_id=1,
                decision_id=1,
                exchange="htx",
                symbol="BTC/USDT",
                side="sell",
                quantity=Decimal("0.01"),
                price=Decimal("60000"),
                market_type="futures_perpetual",
            )

    futures_adapter.place_order.assert_not_called()


@pytest.mark.asyncio
async def test_futures_order_proceeds_when_attestation_present():
    pool = _db_pool_with_execute()
    futures_adapter = AsyncMock()
    futures_adapter.place_order.return_value = "futures-order-1"
    mode = RealExecutionMode(
        db_pool=pool, exchange_adapters={}, futures_exchange_adapters={"htx": futures_adapter}
    )

    with (
        patch("execution_engine.modes.real.is_futures_real_trading_enabled", AsyncMock(return_value=True)),
        patch("execution_engine.modes.real.apply_fill", AsyncMock()) as mocked_apply_fill,
        patch("execution_engine.modes.real.insert_order_row", AsyncMock(return_value=1)),
    ):
        result = await mode.execute(
            risk_check_id=1,
            decision_id=1,
            exchange="htx",
            symbol="BTC/USDT",
            side="sell",
            quantity=Decimal("0.01"),
            price=Decimal("60000"),
            market_type="futures_perpetual",
        )

    futures_adapter.place_order.assert_called_once_with(
        symbol="BTC/USDT", side=PositionSide.SHORT, quantity=Decimal("0.01")
    )
    assert result.status == "filled"
    mocked_apply_fill.assert_called_once()
    assert mocked_apply_fill.call_args.kwargs["market_type"] == "futures_perpetual"


@pytest.mark.asyncio
async def test_spot_order_never_checks_futures_governance():
    """Le spot ne doit jamais être affecté par la porte de gouvernance
    futures - vérifie l'absence totale d'appel à cette vérification."""
    pool = _db_pool_with_execute()
    spot_adapter = AsyncMock()
    spot_adapter.place_order.return_value = "spot-order-1"
    spot_adapter.get_order_status.return_value = {"state": "filled", "filled_amount": "0.01"}
    mode = RealExecutionMode(db_pool=pool, exchange_adapters={"htx": spot_adapter})

    with (
        patch("execution_engine.modes.real.is_futures_real_trading_enabled", AsyncMock()) as mocked_gate,
        patch("execution_engine.modes.real.apply_fill", AsyncMock()),
        patch("execution_engine.modes.real.insert_order_row", AsyncMock(return_value=1)),
    ):
        await mode.execute(
            risk_check_id=1,
            decision_id=1,
            exchange="htx",
            symbol="BTC/USDT",
            side="buy",
            quantity=Decimal("0.01"),
            price=Decimal("60000"),
            market_type="spot",
        )

    mocked_gate.assert_not_called()


@pytest.mark.asyncio
async def test_futures_execute_raises_when_no_futures_adapter_configured_for_exchange():
    pool = _db_pool_with_execute()
    mode = RealExecutionMode(db_pool=pool, exchange_adapters={}, futures_exchange_adapters={})

    with patch("execution_engine.modes.real.is_futures_real_trading_enabled", AsyncMock(return_value=True)):
        with pytest.raises(ValueError, match="Aucun adaptateur futures configuré"):
            await mode.execute(
                risk_check_id=1,
                decision_id=1,
                exchange="htx",
                symbol="BTC/USDT",
                side="sell",
                quantity=Decimal("0.01"),
                price=Decimal("60000"),
                market_type="futures_perpetual",
            )
