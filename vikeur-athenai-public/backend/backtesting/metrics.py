"""Métriques de performance du backtest (Phase 6 : backtest_results ; Phase 14, §4).

Toutes les fonctions sont pures : listes de nombres en entrée, un nombre
en sortie - testables sans base de données ni horloge.
"""

import math

PERIODS_PER_YEAR = 365  # rendements supposés quotidiens pour l'annualisation


def sharpe_ratio(returns: list[float], periods_per_year: int = PERIODS_PER_YEAR) -> float | None:
    """Rendement moyen / écart-type des rendements, annualisé."""
    if len(returns) < 2:
        return None
    mean_return = sum(returns) / len(returns)
    variance = sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)
    std_dev = math.sqrt(variance)
    if std_dev == 0:
        return None
    return (mean_return / std_dev) * math.sqrt(periods_per_year)


def sortino_ratio(returns: list[float], periods_per_year: int = PERIODS_PER_YEAR) -> float | None:
    """Comme Sharpe, mais ne pénalise que la volatilité à la baisse."""
    if len(returns) < 2:
        return None
    mean_return = sum(returns) / len(returns)
    downside_returns = [min(r, 0.0) for r in returns]
    downside_variance = sum(r**2 for r in downside_returns) / len(returns)
    downside_std = math.sqrt(downside_variance)
    if downside_std == 0:
        return None
    return (mean_return / downside_std) * math.sqrt(periods_per_year)


def max_drawdown(equity_curve: list[float]) -> float | None:
    """Perte maximale (en proportion) depuis un sommet antérieur de la courbe d'équité."""
    if len(equity_curve) < 2:
        return None
    peak = equity_curve[0]
    worst_drawdown = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            drawdown = (value - peak) / peak
            worst_drawdown = min(worst_drawdown, drawdown)
    return worst_drawdown  # négatif ou zéro


def calmar_ratio(equity_curve: list[float], periods_per_year: int = PERIODS_PER_YEAR) -> float | None:
    """Rendement annualisé / |Max Drawdown|."""
    if len(equity_curve) < 2:
        return None
    mdd = max_drawdown(equity_curve)
    if mdd is None or mdd == 0:
        return None

    total_return = (equity_curve[-1] - equity_curve[0]) / equity_curve[0]
    num_periods = len(equity_curve) - 1
    annualized_return = (1 + total_return) ** (periods_per_year / num_periods) - 1

    return annualized_return / abs(mdd)


def profit_factor(trade_pnls: list[float]) -> float | None:
    """Somme des gains / |somme des pertes|."""
    gains = sum(p for p in trade_pnls if p > 0)
    losses = sum(p for p in trade_pnls if p < 0)
    if losses == 0:
        return None  # aucune perte -> ratio non défini (pas "infini" par convention ici)
    return gains / abs(losses)


def expectancy(trade_pnls: list[float]) -> float | None:
    """PnL moyen par trade."""
    if not trade_pnls:
        return None
    return sum(trade_pnls) / len(trade_pnls)


def ulcer_index(equity_curve: list[float]) -> float | None:
    """Racine de la moyenne des carrés des drawdowns (pénalise profondeur ET durée)."""
    if len(equity_curve) < 2:
        return None
    peak = equity_curve[0]
    squared_drawdowns = []
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            drawdown_pct = (value - peak) / peak * 100
            squared_drawdowns.append(drawdown_pct**2)
    if not squared_drawdowns:
        return None
    return math.sqrt(sum(squared_drawdowns) / len(squared_drawdowns))
