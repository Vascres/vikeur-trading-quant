"""Comparaison objective des modèles ML (Phase 16, §4).

Réutilise backtesting/metrics.py (Phase 14) pour l'évaluation plutôt que
de dupliquer une logique de calcul de performance.
"""

from dataclasses import dataclass

from backtesting import metrics
from shared.ml_model import MLModel

PREDICTION_THRESHOLD = 0.6  # probabilité minimale pour simuler un trade "long"
ASSUMED_COST_FRACTION = 0.002  # cohérent avec les coûts assumés ailleurs (20 bps, Phase 12/13)


@dataclass(frozen=True)
class ModelEvaluation:
    model_name: str
    profit_factor: float | None
    expectancy: float | None
    total_simulated_trades: int


def evaluate_model(
    model: MLModel, X_validation: list[list[float]], forward_returns: list[float]
) -> ModelEvaluation:
    """Simule un trade "long" à chaque prédiction au-dessus du seuil, sur le
    rendement futur réel déjà connu (jeu de validation) - moins complet
    qu'un backtest bout-en-bout (Phase 14), suffisant pour comparer des
    modèles entre eux (Phase 16, §8).
    """
    probabilities = model.predict_proba(X_validation)
    simulated_pnls = [
        forward_return - ASSUMED_COST_FRACTION
        for probability, forward_return in zip(probabilities, forward_returns)
        if probability >= PREDICTION_THRESHOLD
    ]

    return ModelEvaluation(
        model_name=model.metadata.name,
        profit_factor=metrics.profit_factor(simulated_pnls),
        expectancy=metrics.expectancy(simulated_pnls),
        total_simulated_trades=len(simulated_pnls),
    )


def select_best_model(evaluations: list[ModelEvaluation]) -> ModelEvaluation | None:
    """Sélectionne le modèle avec la meilleure expectancy parmi ceux ayant
    généré au moins quelques trades simulés - ne sert qu'à informer, ne
    déclenche jamais d'activation automatique (Phase 16, §1/§5).
    """
    eligible = [e for e in evaluations if e.total_simulated_trades >= 10 and e.expectancy is not None]
    if not eligible:
        return None
    return max(eligible, key=lambda e: e.expectancy)
