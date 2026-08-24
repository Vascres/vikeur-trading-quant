"""Tests de la Phase 20 : confirmation de remplissage réel.

_poll_fill_confirmation prend désormais l'adaptateur en paramètre
explicite (ADR-0012, multi-exchange) plutôt qu'un attribut unique
`_exchange_adapter` fixé à la construction."""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from execution_engine.modes.real import RealExecutionMode


@pytest.mark.asyncio
async def test_poll_fill_confirmation_returns_filled_when_state_filled():
    mode = RealExecutionMode(db_pool=None, exchange_adapters={})
    adapter = AsyncMock()
    adapter.get_order_status.return_value = {"state": "filled", "filled_amount": "0.01"}

    status, quantity = await mode._poll_fill_confirmation(adapter, "order-123")

    assert status == "filled"
    assert quantity == Decimal("0.01")


@pytest.mark.asyncio
async def test_poll_fill_confirmation_returns_cancelled():
    mode = RealExecutionMode(db_pool=None, exchange_adapters={})
    adapter = AsyncMock()
    adapter.get_order_status.return_value = {"state": "canceled", "filled_amount": None}

    status, quantity = await mode._poll_fill_confirmation(adapter, "order-123")

    assert status == "cancelled"
    assert quantity is None


@pytest.mark.asyncio
async def test_poll_fill_confirmation_gives_up_after_max_attempts(monkeypatch):
    import execution_engine.modes.real as real_module

    monkeypatch.setattr(real_module, "FILL_POLL_INTERVAL_SECONDS", 0)  # accélère le test

    mode = RealExecutionMode(db_pool=None, exchange_adapters={})
    adapter = AsyncMock()
    adapter.get_order_status.return_value = {"state": "submitted", "filled_amount": None}

    status, quantity = await mode._poll_fill_confirmation(adapter, "order-123")

    assert status == "pending"
    assert quantity is None
    assert adapter.get_order_status.call_count == real_module.FILL_POLL_ATTEMPTS
