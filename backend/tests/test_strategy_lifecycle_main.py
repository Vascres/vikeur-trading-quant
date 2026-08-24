"""Tests de strategy_lifecycle.main (Étape 3 du plan validé le 16/08/2026).

Isole l'orchestration (quelle fonction pure est appelée avec quelles
données, quand une transition est appliquée) des fonctions déjà testées
séparément (`test_strategy_lifecycle_metrics.py`,
`test_strategy_lifecycle_eviction_rules.py`,
`test_strategy_lifecycle_repository.py`) via des mocks ciblés.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from strategy_lifecycle.main import evaluate_strategy, run_strategy_lifecycle_cycle
from strategy_lifecycle.metrics import TradeOutcome
from strategy_lifecycle.states import DEGRADED, EXPERIMENTAL


@pytest.mark.asyncio
async def test_evaluate_strategy_no_transition_when_sample_too_small():
    events = []
    with (
        patch("strategy_lifecycle.main.ensure_lifecycle_row", new=AsyncMock()),
        patch("strategy_lifecycle.main.fetch_lifecycle_status", new=AsyncMock(return_value=EXPERIMENTAL)),
        patch("strategy_lifecycle.main.fetch_recent_closed_trades", new=AsyncMock(return_value=[])),
        patch("strategy_lifecycle.main.fetch_reference_capital", new=AsyncMock(return_value=Decimal("350"))),
        patch("strategy_lifecycle.main.apply_transition", new=AsyncMock()) as apply_mock,
    ):
        await evaluate_strategy(
            None, strategy_id=1, exchange="htx", publish_journal_event=lambda t, p: events.append((t, p))
        )

    apply_mock.assert_not_awaited()
    assert events == []


@pytest.mark.asyncio
async def test_evaluate_strategy_applies_eviction_transition_and_publishes_event():
    losing_trades = [TradeOutcome(realized_pnl=Decimal("-1.0"), entry_notional=Decimal("100"))] * 30
    events = []
    with (
        patch("strategy_lifecycle.main.ensure_lifecycle_row", new=AsyncMock()),
        patch("strategy_lifecycle.main.fetch_lifecycle_status", new=AsyncMock(return_value=EXPERIMENTAL)),
        patch(
            "strategy_lifecycle.main.fetch_recent_closed_trades", new=AsyncMock(return_value=losing_trades)
        ),
        patch("strategy_lifecycle.main.fetch_reference_capital", new=AsyncMock(return_value=Decimal("350"))),
        patch("strategy_lifecycle.main.apply_transition", new=AsyncMock()) as apply_mock,
    ):
        await evaluate_strategy(
            None, strategy_id=1, exchange="htx", publish_journal_event=lambda t, p: events.append((t, p))
        )

    apply_mock.assert_awaited_once()
    assert apply_mock.call_args.args[2] == EXPERIMENTAL  # previous_status
    assert apply_mock.call_args.args[3] in (
        "under_review",
        DEGRADED,
    )  # new_status selon l'ampleur de la perte
    assert len(events) == 1
    assert events[0][0] == "strategy_lifecycle.transition"


@pytest.mark.asyncio
async def test_evaluate_strategy_publishes_when_capital_reference_unavailable():
    losing_trades = [TradeOutcome(realized_pnl=Decimal("-1.0"), entry_notional=Decimal("100"))] * 30
    events = []
    with (
        patch("strategy_lifecycle.main.ensure_lifecycle_row", new=AsyncMock()),
        patch("strategy_lifecycle.main.fetch_lifecycle_status", new=AsyncMock(return_value=EXPERIMENTAL)),
        patch(
            "strategy_lifecycle.main.fetch_recent_closed_trades", new=AsyncMock(return_value=losing_trades)
        ),
        patch("strategy_lifecycle.main.fetch_reference_capital", new=AsyncMock(return_value=None)),
        patch("strategy_lifecycle.main.apply_transition", new=AsyncMock()) as apply_mock,
    ):
        await evaluate_strategy(
            None, strategy_id=1, exchange="htx", publish_journal_event=lambda t, p: events.append((t, p))
        )

    apply_mock.assert_not_awaited()
    assert any(t == "strategy_lifecycle.capital_reference_unavailable" for t, _ in events)


@pytest.mark.asyncio
async def test_evaluate_strategy_checks_resurrection_for_degraded_status():
    healthy_quarantine_trades = [
        TradeOutcome(realized_pnl=Decimal("1.0"), entry_notional=Decimal("100"))
    ] * 50
    events = []
    with (
        patch("strategy_lifecycle.main.ensure_lifecycle_row", new=AsyncMock()),
        patch("strategy_lifecycle.main.fetch_lifecycle_status", new=AsyncMock(return_value=DEGRADED)),
        patch(
            "strategy_lifecycle.main.fetch_recent_closed_trades",
            new=AsyncMock(return_value=healthy_quarantine_trades),
        ),
        patch("strategy_lifecycle.main.fetch_reference_capital", new=AsyncMock(return_value=Decimal("350"))),
        patch("strategy_lifecycle.main.fetch_transitioned_at", new=AsyncMock(return_value=None)),
        patch("strategy_lifecycle.main.apply_transition", new=AsyncMock()) as apply_mock,
    ):
        await evaluate_strategy(
            None, strategy_id=1, exchange="htx", publish_journal_event=lambda t, p: events.append((t, p))
        )

    apply_mock.assert_awaited_once()
    assert apply_mock.call_args.args[3] == EXPERIMENTAL  # repromu


@pytest.mark.asyncio
async def test_run_cycle_continues_after_one_strategy_fails():
    """Une erreur sur une stratégie ne doit jamais bloquer l'évaluation
    des autres (même discipline que cost_model/pair_execution)."""
    events = []
    with (
        patch("strategy_lifecycle.main.fetch_active_strategy_ids", new=AsyncMock(return_value=[1, 2])),
        patch(
            "strategy_lifecycle.main.evaluate_strategy",
            new=AsyncMock(side_effect=[RuntimeError("panne"), None]),
        ),
    ):
        await run_strategy_lifecycle_cycle(None, publish_journal_event=lambda t, p: events.append((t, p)))

    assert any(t == "strategy_lifecycle.evaluation_error" for t, _ in events)
