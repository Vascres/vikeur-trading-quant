from shared.decision_engine import DecisionEngine, EngineMetadata, EngineOpinion, Side

DEFAULT_PARAMETERS = {
    "min_abs_momentum": 0.001,  # en dessous, pas de signal directionnel (bruit)
    "min_abs_imbalance": 0.1,  # en dessous, pas de pression carnet suffisante
    "max_spread_bps": 15.0,  # au-dessus, coût trop élevé -> pas de proposition
    "score_floor": 0.5,
    "score_cap": 0.9,  # jamais de quasi-certitude pour une règle simple (Phase 10 §6)
    "momentum_score_weight": 10.0,
    "imbalance_score_weight": 0.2,
    # Confiance fixe et documentée (ADR-0010) : ce moteur à règles fixes
    # n'a aujourd'hui aucune méthode rigoureuse pour mesurer sa propre
    # fiabilité (pas d'historique de performance par régime encore
    # disponible - cf. futur module d'apprentissage continu). Une valeur
    # fixe et modérée est plus honnête qu'une fausse précision inventée.
    "confidence": 0.6,
}


class MomentumImbalanceThreshold(DecisionEngine):
    """Moteur de référence V1 (Phase 10, §6 ; migré vers DecisionEngine
    par ADR-0010) : règles explicites, pas de ML.

    Signal uniquement si momentum et order_flow_imbalance pointent dans le
    même sens, avec un spread acceptable. Sert de point de départ calibrable
    pour le backtesting (Phase 14) - aucune prétention de edge a priori.
    """

    metadata = EngineMetadata(
        name="momentum_imbalance_threshold",
        version=2,  # v1 produisait un StrategyProposal (Strategy) ; v2 produit un EngineOpinion (DecisionEngine, ADR-0010)
        description=(
            "Signal directionnel quand momentum et order_flow_imbalance sont alignés, "
            "filtré par un spread maximal acceptable."
        ),
    )

    def __init__(self, parameters: dict | None = None) -> None:
        self.parameters = {**DEFAULT_PARAMETERS, **(parameters or {})}

    def evaluate(self, features: dict[str, float]) -> EngineOpinion | None:
        momentum = features.get("momentum")
        imbalance = features.get("order_flow_imbalance")
        spread_bps = features.get("spread_bps")
        volatility = features.get("realized_volatility")

        if momentum is None or imbalance is None or spread_bps is None or volatility is None:
            return None  # données insuffisantes - pas une erreur (Phase 9, contrat Feature)

        p = self.parameters

        if abs(momentum) < p["min_abs_momentum"] or abs(imbalance) < p["min_abs_imbalance"]:
            return None  # pas de signal directionnel suffisant

        if spread_bps > p["max_spread_bps"]:
            return None  # coût d'exécution jugé trop élevé

        same_direction = (momentum > 0 and imbalance > 0) or (momentum < 0 and imbalance < 0)
        if not same_direction:
            return None  # désaccord entre tendance de prix et pression du carnet

        if volatility <= 0:
            return None  # pas de risque mesurable -> uncertainty impossible à établir

        suggested_side = Side.BUY if momentum > 0 else Side.SELL

        raw_score = (
            p["score_floor"]
            + abs(momentum) * p["momentum_score_weight"]
            + abs(imbalance) * p["imbalance_score_weight"]
        )
        score = min(raw_score, p["score_cap"])

        return EngineOpinion(
            suggested_side=suggested_side,
            score=score,
            confidence=p["confidence"],
            uncertainty=volatility,
            rationale={
                "momentum": momentum,
                "order_flow_imbalance": imbalance,
                "spread_bps": spread_bps,
                "realized_volatility": volatility,
            },
        )
