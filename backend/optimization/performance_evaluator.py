"""Évaluation de performance par stratégie (Phase 17, §4).

Fonctions pures - réutilisent backtesting/metrics.py (Phase 14), aucune
duplication de la logique de calcul.
"""

from backtesting import metrics

MIN_TRADES_BEFORE_JUDGMENT = 10  # valeur de départ arbitraire (Phase 17, §6), à calibrer


def compute_strategy_score(trade_pnls: list[float]) -> float | None:
    """Espérance mathématique par trade - réutilise metrics.expectancy (Phase 14)."""
    return metrics.expectancy(trade_pnls)


def meets_deactivation_criteria(
    score: float | None, total_trades: int, min_trades: int = MIN_TRADES_BEFORE_JUDGMENT
) -> bool:
    """Une stratégie est désactivée si son espérance est négative sur un
    échantillon jugé suffisant - jamais sur un échantillon trop petit
    (Phase 17, §4).
    """
    if total_trades < min_trades or score is None:
        return False
    return score < 0
