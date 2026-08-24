"""Moteur cross_sectional_momentum (ADR-0017).

Première famille de signal réellement différente des deux moteurs
existants (`momentum_imbalance_threshold`, `order_book_imbalance`), tous
deux en série temporelle (jugent chaque symbole dans l'absolu). Celui-ci
parie sur la persistance du **classement relatif** entre les symboles
suivis, pas sur leur direction absolue - si les 3 symboles suivis
montent tous ensemble, ce moteur ne parie que sur celui qui monte le
plus vite (et contre celui qui monte le moins vite), pas sur les 3.

Consomme `cross_sectional_rank`/`cross_sectional_spread`, calculés une
fois par cycle par `meta_engine/cross_sectional.py` (pas par ce moteur
lui-même, qui reste une fonction pure de `features -> EngineOpinion`
comme tout `DecisionEngine`, ADR-0002) et injectés dans le dict
`features` avant l'appel à `evaluate()` (cf. `decision_engine/main.py`).

Limite assumée (ADR-0017 §6) : à seulement 3 symboles suivis, ce n'est
pas un vrai classement cross-sectionnel par déciles (pratique classique
à plus grande échelle) - une version minimale à 3 positions, suffisante
pour prouver le mécanisme, pas la version définitive.
"""

from shared.decision_engine import DecisionEngine, EngineMetadata, EngineOpinion, Side

DEFAULT_PARAMETERS = {
    # En dessous, l'écart leader-retardataire n'est qu'un bruit entre
    # valeurs de momentum proches, pas une vraie divergence de force
    # (ADR-0017 §3) - seuil de départ, à calibrer une fois un historique
    # réel accumulé (même esprit que les seuils de départ des deux
    # moteurs existants, jamais présentés comme définitifs).
    "min_spread_threshold": 0.002,
    "score_floor": 0.5,
    "score_cap": 0.85,
    "spread_score_weight": 20.0,
    # Confiance croissante avec la dispersion réelle observée (pas fixe
    # comme les deux moteurs existants) - normalisée par
    # `confidence_normalization_spread`, plafonnée à `max_confidence`.
    "confidence_normalization_spread": 0.02,
    "max_confidence": 0.7,
}


class CrossSectionalMomentum(DecisionEngine):
    """Signal directionnel basé sur le rang de momentum relatif entre les
    symboles suivis, pas sur le momentum absolu d'un seul symbole."""

    metadata = EngineMetadata(
        name="cross_sectional_momentum",
        version=1,
        description=(
            "Classe les symboles suivis par momentum relatif ; parie sur la persistance du "
            "classement (leader continue de surperformer, retardataire de sous-performer), "
            "pas sur la direction absolue d'un symbole isolé."
        ),
    )

    def __init__(self, parameters: dict | None = None) -> None:
        self.parameters = {**DEFAULT_PARAMETERS, **(parameters or {})}

    def evaluate(self, features: dict[str, float]) -> EngineOpinion | None:
        rank = features.get("cross_sectional_rank")
        spread = features.get("cross_sectional_spread")
        volatility = features.get("realized_volatility")

        if rank is None or spread is None or volatility is None:
            return None  # données insuffisantes (univers pas encore prêt, ou cycle sans injection)

        p = self.parameters

        if rank == 0.0:
            return None  # symbole "du milieu" - ni assez leader ni assez retardataire pour un pari

        if spread < p["min_spread_threshold"]:
            return None  # dispersion trop faible entre symboles - classement non significatif

        if volatility <= 0:
            return None  # pas de risque mesurable -> uncertainty impossible à établir

        suggested_side = Side.BUY if rank > 0 else Side.SELL

        raw_score = p["score_floor"] + spread * p["spread_score_weight"]
        score = min(raw_score, p["score_cap"])

        confidence = min(spread / p["confidence_normalization_spread"], p["max_confidence"])

        return EngineOpinion(
            suggested_side=suggested_side,
            score=score,
            confidence=confidence,
            uncertainty=volatility,
            rationale={
                "cross_sectional_rank": rank,
                "cross_sectional_spread": spread,
                "realized_volatility": volatility,
            },
        )
