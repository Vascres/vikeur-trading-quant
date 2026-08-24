"""Construction d'une série de rendements journaliers et d'une courbe
d'équité à partir de trades clôturés (chantier Strategy Dashboard,
16/08/2026 - Sharpe/Sortino/Calmar, mandat §14).

Fonction pure, testée en isolation - aucun accès DB/réseau/horloge.

Regroupe les trades par JOUR de clôture, jamais un rendement par trade
utilisé directement comme s'il était journalier : `backtesting/
metrics.py` (`sharpe_ratio`, `sortino_ratio`, `calmar_ratio`) annualise
avec `sqrt(365)` en supposant explicitement des rendements quotidiens
("rendements supposés quotidiens pour l'annualisation", cf. sa propre
docstring) - lui fournir directement des rendements par trade produirait
un facteur d'annualisation faux dès que la fréquence de trading diffère
d'un trade par jour exactement. Le regroupement quotidien ici respecte
cette hypothèse plutôt que de la contourner silencieusement.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date


def build_daily_returns_and_equity_curve(
    trade_pnls_by_close_date: list[tuple[date, float]], starting_equity: float = 100.0
) -> tuple[list[float], list[float]]:
    """`trade_pnls_by_close_date` : une entrée par trade clôturé, ordre
    quelconque (regroupé et trié ici). Retourne `(rendements_quotidiens,
    courbe_equity)` - la courbe démarre à `starting_equity` et compte un
    point de plus que la liste de rendements (le point de départ,
    convention identique à `backtesting.portfolio.BacktestPortfolio.
    equity_curve`)."""
    daily_pnl: dict[date, float] = defaultdict(float)
    for close_date, pnl in trade_pnls_by_close_date:
        daily_pnl[close_date] += pnl

    returns: list[float] = []
    equity_curve: list[float] = [starting_equity]
    equity = starting_equity

    for day in sorted(daily_pnl):
        pnl = daily_pnl[day]
        pct_return = pnl / equity if equity > 0 else 0.0
        returns.append(pct_return)
        equity += pnl
        equity_curve.append(equity)

    return returns, equity_curve
