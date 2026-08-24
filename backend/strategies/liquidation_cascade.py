"""Moteur liquidation_cascade (chantier Liquidation Cascade, 16/08/2026 -
mandat §28, "moteur phare" candidat "si elles se démarquent réellement").

Thèse de mean-reversion : une cascade de liquidations forcées (beaucoup
de positions à levier fermées de force dans un court laps de temps) crée
souvent une dislocation de prix temporaire, indépendante de la valeur
fondamentale - le marché "punit" au-delà de ce que justifierait
l'information disponible, puis revient partiellement. Ce moteur parie
sur ce retour, jamais sur la poursuite de la tendance qui a déclenché la
cascade.

Se déclenche seulement si DEUX conditions sont réunies simultanément :
une intensité de liquidation notable (`liquidation_cascade_intensity`)
ET un mouvement de prix notable dans le même cycle (`momentum`) - une
chute de prix sans liquidation notable n'est pas une cascade ; une
liquidation isolée sans mouvement de prix significatif n'en est pas une
non plus. Achète après une cascade qui a fait CHUTER le prix (mean-
reversion à la hausse), vend après une cascade qui l'a fait MONTER
(mean-reversion à la baisse - typiquement des positions courtes
liquidées lors d'un short squeeze).

Limitation assumée et documentée (`feature_engine/features/
liquidation_cascade_intensity.py`) : `momentum` est aujourd'hui calculé
à partir du prix SPOT (seul flux de marché actuellement collecté en
continu, cf. `data_collector`), alors que les liquidations elles-mêmes
sont un phénomène FUTURES. Un proxy raisonnable (spot et futures restent
fortement corrélés pour les actifs majeurs) mais pas une correspondance
parfaite - à corriger le jour où la collecte de prix futures en temps
réel existera.

Tous les seuils ci-dessous sont des valeurs de DÉPART, jamais calibrées
empiriquement : `liquidation_ingest` vient d'être déployé (16/08/2026),
aucun historique réel de cascade n'existe encore au moment de
l'écriture. La confiance délibérément basse (0.4, plus basse que les 3
moteurs directionnels déjà actifs) reflète cette absence de preuve -
jamais un excès de confiance sur un moteur non éprouvé.

IMPORTANT - câblage dans le pipeline fusionné (16/08/2026) : ce moteur
est désormais dans `strategies/registry.py::ACTIVE_STRATEGIES`, avec
`market_type="futures_perpetual"` (EngineMetadata) - `decision_engine/
main.py` fusionne désormais ses avis SÉPARÉMENT des 3 moteurs spot déjà
actifs (jamais mélangés dans une même décision), et marque explicitement
la `meta_decision`/`decision` résultante comme `futures_perpetual`.
Démarre au statut EXPERIMENTAL (Strategy Lifecycle, Étape 3) dès son
enregistrement - paper uniquement, jamais de capital réel tant qu'il
n'aura pas démontré d'espérance nette positive sur un échantillon réel
(aucune donnée de calibration n'existe encore au 16/08/2026)."""

from shared.decision_engine import DecisionEngine, EngineMetadata, EngineOpinion, Side

DEFAULT_PARAMETERS = {
    # Valeur de départ, jamais calibrée (aucune donnée réelle au 16/08/2026,
    # cf. docstring du module) - un ordre de grandeur retenu pour ne
    # réagir qu'à des liquidations notables, pas au bruit de fond.
    "min_liquidation_notional_usd": 50_000.0,
    "min_abs_momentum": 0.01,  # 1% de mouvement sur la fenêtre de la feature momentum
    "max_spread_bps": 30.0,
    "score_floor": 0.5,
    "score_cap": 0.9,
    # Confiance délibérément prudente (cf. docstring du module) -
    # nettement plus basse que les moteurs directionnels déjà actifs
    # (0.5-0.6 habituellement) tant qu'aucune preuve empirique n'existe.
    "confidence": 0.4,
}


class LiquidationCascadeAgent(DecisionEngine):
    metadata = EngineMetadata(
        name="liquidation_cascade",
        version=1,
        description=(
            "Mean-reversion après une cascade de liquidations détectée "
            "(notionnel liquidé + mouvement de prix simultanés)."
        ),
        # Aucune restriction de régime pour l'instant - une cascade de
        # liquidations est par construction un événement de forte
        # volatilité, restreindre aux régimes déjà connus comme
        # "volatils" présupposerait une classification qui n'a jamais
        # été vérifiée empiriquement contre ce signal précis.
        allowed_regimes=frozenset(),
        # Marché visé (chantier de routage, 16/08/2026) : les
        # liquidations sont un phénomène de levier, ce moteur n'a de
        # sens économique que sur futures - jamais mélangé avec les 3
        # moteurs spot déjà actifs dans une même fusion
        # (decision_engine groupe désormais par market_type).
        market_type="futures_perpetual",
    )

    def __init__(self, parameters: dict | None = None) -> None:
        self.parameters = {**DEFAULT_PARAMETERS, **(parameters or {})}

    def evaluate(self, features: dict[str, float]) -> EngineOpinion | None:
        liquidation_notional = features.get("liquidation_cascade_intensity")
        momentum = features.get("momentum")
        spread_bps = features.get("spread_bps")

        if liquidation_notional is None or momentum is None or spread_bps is None:
            return None  # données insuffisantes - pas une erreur

        p = self.parameters

        if liquidation_notional < p["min_liquidation_notional_usd"]:
            return None  # pas assez de notionnel liquidé pour parler de cascade

        if abs(momentum) < p["min_abs_momentum"]:
            return None  # mouvement de prix insuffisant pour parler de cascade

        if spread_bps > p["max_spread_bps"]:
            return None  # coût d'exécution jugé trop élevé

        if spread_bps <= 0:
            return None  # pas de mesure d'incertitude fiable

        # Mean-reversion, jamais un suivi de tendance : un mouvement
        # négatif fort (cascade de longs liquidés) -> on ACHÈTE, pari
        # sur le rebond. Un mouvement positif fort (cascade de courts
        # liquidés, short squeeze) -> on VEND.
        suggested_side = Side.BUY if momentum < 0 else Side.SELL

        raw_score = p["score_floor"] + min(abs(momentum), 0.10) * 2.0
        score = min(raw_score, p["score_cap"])

        return EngineOpinion(
            suggested_side=suggested_side,
            score=score,
            confidence=p["confidence"],
            uncertainty=spread_bps / 10_000,
            rationale={
                "liquidation_cascade_intensity": liquidation_notional,
                "momentum": momentum,
                "spread_bps": spread_bps,
            },
        )
