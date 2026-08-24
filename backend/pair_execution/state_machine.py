"""Machine à états de l'exécution de paire (ADR-0021 §4.5-§4.6).

Fonctions pures - la logique de décision (quel état suit quel résultat,
quand tenter une complétion, quand bloquer un symbole) est testée en
isolation, séparée de l'orchestration asynchrone réelle (I/O exchange,
DB) qui l'utilise dans `pair_execution/main.py`. C'est le cœur du
chantier : jamais une simple règle "les deux ordres doivent réussir",
un vrai raisonnement sur ce qu'il faut faire dans chaque cas.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PairStatus(str, Enum):
    PENDING_VALIDATION = "pending_validation"
    VALIDATED = "validated"
    EXECUTING = "executing"
    BOTH_FILLED = "both_filled"
    BOTH_REJECTED = "both_rejected"
    PARTIAL_EXECUTION = "partial_execution"
    COMPLETING_MISSING_LEG = "completing_missing_leg"
    COMPENSATING = "compensating"
    RESOLVED = "resolved"


class LegOutcome(str, Enum):
    FILLED = "filled"
    REJECTED = "rejected"


class ResolutionAction(str, Enum):
    COMPLETED_MISSING_LEG = "completed_missing_leg"
    COMPENSATED_OPEN_LEG = "compensated_open_leg"
    UNRESOLVED = "unresolved"


# États qui doivent bloquer toute nouvelle paire sur le même symbole
# (ADR-0021 §4.6) - tant qu'une exposition résiduelle existe ou est en
# cours de résolution, jamais une seconde paire ouverte en parallèle
# sur ce symbole.
BLOCKING_STATUSES = frozenset(
    {PairStatus.PARTIAL_EXECUTION, PairStatus.COMPLETING_MISSING_LEG, PairStatus.COMPENSATING}
)


def determine_execution_outcome(leg_a_outcome: LegOutcome, leg_b_outcome: LegOutcome) -> PairStatus:
    """Détermine l'état immédiatement après la tentative d'exécution
    parallèle des deux jambes en FOK (ADR-0021 §2 option E) - chaque
    jambe est un résultat binaire (remplie ou rejetée), jamais un
    remplissage partiel d'une seule jambe (garanti par FOK)."""
    if leg_a_outcome == LegOutcome.FILLED and leg_b_outcome == LegOutcome.FILLED:
        return PairStatus.BOTH_FILLED
    if leg_a_outcome == LegOutcome.REJECTED and leg_b_outcome == LegOutcome.REJECTED:
        return PairStatus.BOTH_REJECTED
    return PairStatus.PARTIAL_EXECUTION


@dataclass(frozen=True)
class CompletionDecision:
    should_attempt: bool
    reason: str


def decide_completion_attempt(
    *,
    current_net_edge_bps: float,
    original_net_edge_bps: float,
    max_edge_degradation_bps: float,
    attempts_made: int,
    max_attempts: int,
) -> CompletionDecision:
    """Décide si une tentative de complétion de la jambe manquante est
    sûre (ADR-0021 §4.5) - jamais un renvoi aveugle du même ordre.
    Revérifie l'edge courant contre l'edge d'origine : si le marché a
    trop bougé depuis la première tentative, mieux vaut compenser
    (revenir à plat) que de forcer une complétion à un edge dégradé."""
    if attempts_made >= max_attempts:
        return CompletionDecision(
            should_attempt=False,
            reason=f"nombre maximal de tentatives atteint ({attempts_made}/{max_attempts})",
        )

    edge_degradation_bps = original_net_edge_bps - current_net_edge_bps
    if edge_degradation_bps > max_edge_degradation_bps:
        return CompletionDecision(
            should_attempt=False,
            reason=(
                f"edge dégradé de {edge_degradation_bps:.2f} bps depuis la validation initiale, "
                f"au-delà du seuil autorisé ({max_edge_degradation_bps:.2f} bps) - compensation "
                "préférée à une complétion forcée."
            ),
        )

    return CompletionDecision(should_attempt=True, reason="edge encore acceptable, tentative autorisée")


def is_symbol_blocked_by_unresolved_pair(open_pair_statuses: list[PairStatus]) -> bool:
    """ADR-0021 §4.6 - vérifiée avant même la première étape de la
    validation pré-trade d'une nouvelle paire sur ce symbole."""
    return any(status in BLOCKING_STATUSES for status in open_pair_statuses)


@dataclass(frozen=True)
class IncidentRecord:
    """Ce qui doit être journalisé pour tout épisode de PARTIAL_EXECUTION
    (ADR-0021 - "mesurer le coût réel de chaque incident d'exécution"),
    quelle que soit son issue finale."""

    filled_leg: str  # 'spot' | 'futures_perpetual'
    missing_leg: str
    residual_exposure_notional: float
    resolution_action: ResolutionAction
    realized_cost_bps: float | None  # None tant que non résolu


def build_incident_record(
    *,
    filled_leg_market_type: str,
    missing_leg_market_type: str,
    residual_exposure_notional: float,
    resolution_action: ResolutionAction,
    realized_cost_bps: float | None = None,
) -> IncidentRecord:
    """Construit l'enregistrement d'incident - fonction pure, séparée de
    la persistance réelle (`pair_execution/main.py`), pour rester
    testable sans DB."""
    return IncidentRecord(
        filled_leg=filled_leg_market_type,
        missing_leg=missing_leg_market_type,
        residual_exposure_notional=residual_exposure_notional,
        resolution_action=resolution_action,
        realized_cost_bps=realized_cost_bps,
    )
