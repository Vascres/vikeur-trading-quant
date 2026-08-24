"""Seuils de décision (Phase 1, §3 ; Phase 11, §5 ; ADR-0010) et fonctions
pures associées.

Séparées du reste de la boucle d'orchestration pour rester testables en
isolation (exigence de la Phase 1 : "chaque module facilement testable").

`evaluate_verdict` prend désormais des valeurs scalaires directes
(ADR-0010) plutôt qu'un `StrategyProposal` - ce dernier est déprécié,
et une `MetaDecision` (fusion + calibration) n'a plus la même forme
qu'une proposition de stratégie individuelle.
"""

from datetime import datetime, timedelta

DECISION_THRESHOLDS = {
    "min_success_probability": 0.55,
    "min_expected_value": 0.0,  # doit être strictement positif
    "min_risk_reward_ratio": 1.5,
}

# ADR-0014 : seuils du verdict de démarrage ("bootstrap"), utilisés
# uniquement en mode paper quand la calibration active est au niveau
# 'collecting' du Confidence Lifecycle (ADR-0015) - aucune probabilité
# disponible encore, donc arbitrage sur le score brut fusionné plutôt
# que sur une probabilité calibrée. Seuil de score délibérément plus
# strict que ne le serait une probabilité de 0.55, pour compenser
# l'absence de toute validation statistique - jamais utilisé en mode
# réel (cf. decision_engine/main.py).
BOOTSTRAP_THRESHOLDS = {
    "min_fused_score": 0.75,
    "min_expected_value": 0.0,
    "min_risk_reward_ratio": 1.5,
}

FEATURE_FRESHNESS_SECONDS = 120  # double de l'intervalle de calcul du Feature Builder (Phase 9)


def evaluate_verdict(
    success_probability: float,
    expected_value: float,
    risk_reward_ratio: float,
    thresholds: dict = DECISION_THRESHOLDS,
) -> str:
    """Retourne 'signal' ou 'no_signal' selon les seuils de la Phase 1, §3.

    Fonction pure : aucun accès DB/horloge, testable directement.
    """
    passes_probability = success_probability >= thresholds["min_success_probability"]
    passes_expected_value = expected_value > thresholds["min_expected_value"]
    passes_risk_reward = risk_reward_ratio >= thresholds["min_risk_reward_ratio"]

    if passes_probability and passes_expected_value and passes_risk_reward:
        return "signal"
    return "no_signal"


def evaluate_bootstrap_verdict(
    fused_score: float,
    expected_value: float,
    risk_reward_ratio: float,
    thresholds: dict = BOOTSTRAP_THRESHOLDS,
) -> str:
    """Retourne 'signal' ou 'no_signal' à partir du score brut fusionné,
    plutôt que d'une probabilité calibrée (ADR-0014).

    Fonction pure, même structure que `evaluate_verdict` - seule la
    grandeur évaluée diffère (score brut vs probabilité calibrée).
    L'appelant (`decision_engine/main.py`) est seul responsable de ne
    jamais invoquer cette fonction en dehors du mode d'exécution paper.
    """
    passes_score = fused_score >= thresholds["min_fused_score"]
    passes_expected_value = expected_value > thresholds["min_expected_value"]
    passes_risk_reward = risk_reward_ratio >= thresholds["min_risk_reward_ratio"]

    if passes_score and passes_expected_value and passes_risk_reward:
        return "signal"
    return "no_signal"


def is_data_fresh(
    latest_feature_time: datetime,
    now: datetime,
    max_age_seconds: int = FEATURE_FRESHNESS_SECONDS,
) -> bool:
    """Vérifie qu'une feature n'est pas périmée (Phase 11, §6)."""
    return (now - latest_feature_time) <= timedelta(seconds=max_age_seconds)


# --- Étape 3 (16/08/2026) : Strategy Lifecycle - filtrage de la fusion ---

# Dupliqué de `strategy_lifecycle.states` plutôt qu'importé : ce module
# ne dépend jamais du package `strategy_lifecycle` (contrat import-linter
# 13, même principe que `fee_schedule`/`cost_model` - le statut est lu en
# SQL direct par `decision_engine/main.py`, jamais par un import).
LIVE_ELIGIBLE_LIFECYCLE_STATUSES = {"validated", "production", "under_review"}
ALWAYS_EXCLUDED_LIFECYCLE_STATUSES = {"registered", "collecting", "suspended", "deprecated"}


def is_excluded_from_fusion(lifecycle_status: str | None, execution_mode: str) -> bool:
    """Décide si l'avis d'un moteur doit être exclu de la fusion selon son
    statut de Strategy Lifecycle et le mode d'exécution courant. Fonction
    pure - le statut est déjà résolu par l'appelant.

    - Statut inconnu (ligne pas encore initialisée) : jamais exclu en
      paper (comportement historique, avant ce chantier), toujours
      exclu en réel (aucune preuve de rentabilité disponible - Principe
      3 du mandat : "un moteur non validé ne doit pas être traité comme
      s'il avait déjà démontré sa rentabilité").
    - REGISTERED/COLLECTING/SUSPENDED/DEPRECATED : toujours exclus, quel
      que soit le mode.
    - DEGRADED : exclu seulement en réel - continue de trader en paper
      (mandat : "elle continue de tourner en Paper pour voir si elle se
      rétablit").
    - EXPERIMENTAL : exclu seulement en réel (paper uniquement par
      définition du statut).
    - VALIDATED/PRODUCTION/UNDER_REVIEW : jamais exclus.
    """
    if lifecycle_status is None:
        return execution_mode == "real"
    if lifecycle_status in ALWAYS_EXCLUDED_LIFECYCLE_STATUSES:
        return True
    if execution_mode == "real":
        return lifecycle_status not in LIVE_ELIGIBLE_LIFECYCLE_STATUSES
    return False
