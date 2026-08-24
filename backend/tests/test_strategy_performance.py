"""Tests de shared.strategy_performance (chantier Strategy Dashboard, 16/08/2026)."""

from __future__ import annotations

from datetime import date

from shared.strategy_performance import build_daily_returns_and_equity_curve


def test_empty_input_yields_only_the_starting_point():
    returns, equity_curve = build_daily_returns_and_equity_curve([], starting_equity=100.0)
    assert returns == []
    assert equity_curve == [100.0]


def test_single_trade_produces_one_return_and_two_equity_points():
    returns, equity_curve = build_daily_returns_and_equity_curve(
        [(date(2026, 8, 16), 10.0)], starting_equity=100.0
    )
    assert returns == [0.10]
    assert equity_curve == [100.0, 110.0]


def test_multiple_trades_same_day_are_summed_into_one_daily_return():
    returns, equity_curve = build_daily_returns_and_equity_curve(
        [(date(2026, 8, 16), 5.0), (date(2026, 8, 16), 5.0)], starting_equity=100.0
    )
    assert returns == [0.10]  # 10 / 100, un seul point pour la journée
    assert equity_curve == [100.0, 110.0]


def test_trades_across_multiple_days_are_ordered_chronologically_regardless_of_input_order():
    returns, equity_curve = build_daily_returns_and_equity_curve(
        [(date(2026, 8, 17), 10.0), (date(2026, 8, 16), 10.0)],  # ordre inversé en entrée
        starting_equity=100.0,
    )
    assert equity_curve == [100.0, 110.0, 120.0]  # jour 16 puis jour 17 (+10 chacun), jamais l'inverse


def test_a_losing_day_reduces_equity_and_produces_a_negative_return():
    returns, equity_curve = build_daily_returns_and_equity_curve(
        [(date(2026, 8, 16), -20.0)], starting_equity=100.0
    )
    assert returns == [-0.20]
    assert equity_curve == [100.0, 80.0]


def test_zero_or_negative_equity_never_causes_a_division_by_zero():
    returns, equity_curve = build_daily_returns_and_equity_curve(
        [(date(2026, 8, 16), -100.0), (date(2026, 8, 17), 5.0)], starting_equity=100.0
    )
    assert equity_curve[1] == 0.0  # équité tombée à zéro
    assert returns[1] == 0.0  # pas de ZeroDivisionError, jamais une valeur inventée
