"""Moteur order_book_imbalance (ADR-0010).

Deuxième moteur spécialisé, ajouté uniquement pour prouver le motif de
fusion multi-moteurs sur un cas réel (ADR-0006, chantier 4) - **aucune
prétention d'avantage statistique a priori** (principe fondamental de la
mission). Contrairement à `momentum_imbalance_threshold`, ce moteur ne
regarde que la pression du carnet d'ordres (`order_flow_imbalance`),
indépendamment de la tendance de prix - un signal généalogiquement
différent, condition nécessaire pour que la fusion ait un sens (fusionner
deux copies du même signal n'apporterait rien).
"""

from shared.decision_engine import DecisionEngine, EngineMetadata, EngineOpinion, Side

DEFAULT_PARAMETERS = {
    "min_abs_imbalance": 0.15,  # légèrement plus strict que le premier moteur (Phase 10 §6, même esprit)
    "max_spread_bps": 20.0,
    "score_floor": 0.5,
    "score_cap": 0.85,
    "imbalance_score_weight": 0.3,
    # Confiance fixe et documentée (ADR-0010, même limitation assumée que
    # momentum_imbalance_threshold) - volontairement différente pour que
    # la fusion pondérée ait un effet observable entre les deux moteurs.
    "confidence": 0.5,
}


class OrderBookImbalance(DecisionEngine):
    """Signal directionnel basé uniquement sur la pression du carnet
    d'ordres, filtré par un spread maximal acceptable. Comme
    `momentum_imbalance_threshold`, sert de point de départ calibrable
    pour le backtesting - aucune prétention de edge a priori (Phase 10, §6)."""

    metadata = EngineMetadata(
        name="order_book_imbalance",
        version=1,
        description="Signal directionnel basé sur order_flow_imbalance seul, filtré par le spread.",
    )

    def __init__(self, parameters: dict | None = None) -> None:
        self.parameters = {**DEFAULT_PARAMETERS, **(parameters or {})}

    def evaluate(self, features: dict[str, float]) -> EngineOpinion | None:
        imbalance = features.get("order_flow_imbalance")
        spread_bps = features.get("spread_bps")

        if imbalance is None or spread_bps is None:
            return None  # données insuffisantes - pas une erreur

        p = self.parameters

        if abs(imbalance) < p["min_abs_imbalance"]:
            return None  # pression du carnet insuffisante

        if spread_bps > p["max_spread_bps"]:
            return None  # coût d'exécution jugé trop élevé

        if spread_bps <= 0:
            return None  # pas de mesure d'incertitude fiable

        suggested_side = Side.BUY if imbalance > 0 else Side.SELL

        raw_score = p["score_floor"] + abs(imbalance) * p["imbalance_score_weight"]
        score = min(raw_score, p["score_cap"])

        return EngineOpinion(
            suggested_side=suggested_side,
            score=score,
            confidence=p["confidence"],
            uncertainty=spread_bps / 10_000,  # proxy de microstructure, distinct de la volatilité
            rationale={"order_flow_imbalance": imbalance, "spread_bps": spread_bps},
        )
