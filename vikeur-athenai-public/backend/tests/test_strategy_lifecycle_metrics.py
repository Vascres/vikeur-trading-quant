"""Tests de strategy_lifecycle.metrics (Étape 3 du plan validé le 16/08/2026)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from strategy_lifecycle.metrics import TradeOutcome, compute_lifecycle_metrics


def test_empty_trade_list_yields_neutral_metrics():
    metrics = compute_lifecycle_metrics([])
    assert metrics.sample_size == 0
    assert metrics.ev_net_bps is None
    assert metrics.cumulative_pnl == Decimal(0)
    assert metrics.profit_factor is None


def test_ev_net_bps_is_the_average_of_per_trade_bps():
    trades = [
        TradeOutcome(realized_pnl=Decimal("1.0"), entry_notional=Decimal("100")),  # +100 bps
        TradeOutcome(realized_pnl=Decimal("-0.5"), entry_notional=Decimal("100")),  # -50 bps
    ]
    metrics = compute_lifecycle_metrics(trades)
    assert metrics.ev_net_bps == pytest.approx(25.0)  # (100 - 50) / 2
    assert metrics.sample_size == 2


def test_cumulative_pnl_sums_realized_pnl_regardless_of_notional():
    trades = [
        TradeOutcome(realized_pnl=Decimal("2.5"), entry_notional=Decimal("50")),
        TradeOutcome(realized_pnl=Decimal("-1.0"), entry_notional=Decimal("200")),
    ]
    metrics = compute_lifecycle_metrics(trades)
    assert metrics.cumulative_pnl == Decimal("1.5")


def test_profit_factor_is_gross_wins_over_absolute_gross_losses():
    trades = [
        TradeOutcome(realized_pnl=Decimal("3.0"), entry_notional=Decimal("100")),
        TradeOutcome(realized_pnl=Decimal("1.0"), entry_notional=Decimal("100")),
        TradeOutcome(realized_pnl=Decimal("-2.0"), entry_notional=Decimal("100")),
    ]
    metrics = compute_lifecycle_metrics(trades)
    assert metrics.profit_factor == pytest.approx(2.0)  # (3+1) / 2


def test_profit_factor_none_when_no_losing_trade():
    trades = [TradeOutcome(realized_pnl=Decimal("1.0"), entry_notional=Decimal("100"))]
    metrics = compute_lifecycle_metrics(trades)
    assert (
        metrics.profit_factor is None
    )  # pas de division par zéro, jamais un "profit factor infini" trompeur


def test_trades_with_zero_entry_notional_excluded_from_ev_bps_but_not_from_cumulative_pnl():
    """Un notionnel d'entrée nul/inconnu ne doit jamais produire une
    division par zéro ni fausser silencieusement la moyenne bps - il est
    exclu du calcul de bps, mais son P&L reste compté dans le cumul
    (source de vérité pour le drawdown)."""
    trades = [
        TradeOutcome(realized_pnl=Decimal("5.0"), entry_notional=Decimal("0")),
        TradeOutcome(realized_pnl=Decimal("1.0"), entry_notional=Decimal("100")),
    ]
    metrics = compute_lifecycle_metrics(trades)
    assert metrics.ev_net_bps == pytest.approx(100.0)  # seul le second trade contribue (1.0/100*10000)
    assert metrics.cumulative_pnl == Decimal("6.0")  # les deux trades comptent
    assert metrics.sample_size == 2
