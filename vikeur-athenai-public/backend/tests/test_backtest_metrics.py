"""Tests de la Phase 14 : métriques de performance (fonctions pures)."""

import pytest

from backtesting import metrics


def test_sharpe_ratio_zero_volatility_returns_none():
    assert metrics.sharpe_ratio([0.01, 0.01, 0.01]) is None


def test_sharpe_ratio_positive_returns():
    result = metrics.sharpe_ratio([0.01, 0.02, -0.01, 0.015], periods_per_year=365)
    assert result is not None
    assert result > 0


def test_sharpe_ratio_insufficient_data_returns_none():
    assert metrics.sharpe_ratio([0.01]) is None


def test_sortino_ignores_upside_volatility():
    # Deux séries avec la même moyenne mais l'une avec plus de volatilité haussière -
    # le Sortino ne doit pénaliser que les rendements négatifs.
    low_upside_vol = [0.01, 0.01, -0.02, 0.01]
    high_upside_vol = [0.01, 0.05, -0.02, -0.02]
    sortino_low = metrics.sortino_ratio(low_upside_vol)
    sortino_high = metrics.sortino_ratio(high_upside_vol)
    assert sortino_low is not None and sortino_high is not None


def test_max_drawdown_detects_worst_drop():
    equity = [100, 120, 90, 110, 80, 130]
    result = metrics.max_drawdown(equity)
    # pire drawdown : 120 -> 80 = -33.33%
    assert result == pytest.approx(-1 / 3, rel=1e-3)


def test_max_drawdown_no_drop_is_zero():
    equity = [100, 110, 120, 130]
    assert metrics.max_drawdown(equity) == pytest.approx(0.0)


def test_calmar_ratio_requires_nonzero_drawdown():
    equity = [100, 110, 120, 130]  # jamais de drawdown
    assert metrics.calmar_ratio(equity) is None


def test_calmar_ratio_basic_case():
    equity = [100, 150, 120]  # gain puis drawdown
    result = metrics.calmar_ratio(equity, periods_per_year=365)
    assert result is not None


def test_profit_factor_no_losses_returns_none():
    assert metrics.profit_factor([10, 20, 30]) is None


def test_profit_factor_basic_case():
    result = metrics.profit_factor([100, -50, 50, -25])
    assert result == pytest.approx(150 / 75)


def test_expectancy_basic_case():
    assert metrics.expectancy([10, -5, 20, -5]) == pytest.approx(5.0)


def test_expectancy_empty_returns_none():
    assert metrics.expectancy([]) is None


def test_ulcer_index_zero_when_no_drawdown():
    equity = [100, 110, 120, 130]
    assert metrics.ulcer_index(equity) == pytest.approx(0.0)


def test_ulcer_index_positive_when_drawdown_present():
    equity = [100, 120, 90, 130]
    result = metrics.ulcer_index(equity)
    assert result is not None
    assert result > 0
