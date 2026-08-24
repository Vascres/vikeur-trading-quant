"""Execution Risk Score et Pair Quality Score (ADR-0021 §4.3).

Fonction pure - traduit directement la formule de l'architecture
validée : l'espérance nette de la paire entière, après ajustement pour
le risque d'exécution (probabilité de remplissage des deux jambes ET
coût attendu d'une éventuelle exécution partielle), pas seulement
l'edge brut mesuré.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ExecutionRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PairDecisionOutcome(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"


# Seuils de catégorisation du risque d'exécution (ADR-0021 §4.3) -
# valeurs de départ prudentes sur la probabilité de remplissage de la
# paire entière, à calibrer avec des données réelles.
_EXECUTION_RISK_LOW_THRESHOLD = 0.95
_EXECUTION_RISK_MEDIUM_THRESHOLD = 0.85

# Marge de sécurité minimale exigée sur l'espérance nette après risque -
# volontairement croissante avec le niveau de risque, pas un seuil fixe
# à zéro : une espérance positive mais faible sur une paire à risque
# d'exécution élevé n'est pas acceptable de la même façon qu'une
# espérance équivalente sur une paire à risque faible (cf. l'exemple
# SOL de la conception - EV positive mais risque HIGH -> REJECT malgré
# tout). Valeurs de départ prudentes, à calibrer.
MIN_PAIR_QUALITY_SCORE_BPS_BY_RISK: dict[ExecutionRisk, float] = {
    ExecutionRisk.LOW: 0.0,
    ExecutionRisk.MEDIUM: 5.0,
    ExecutionRisk.HIGH: 20.0,
}


@dataclass(frozen=True)
class LegAssessment:
    market_type: str  # 'spot' | 'futures_perpetual'
    fee_bps: float
    slippage_bps: float
    fill_probability: float  # cf. liquidity_simulator.estimate_fill_probability


@dataclass(frozen=True)
class PairQualityAssessment:
    gross_edge_bps: float
    fees_bps: float
    slippage_bps: float
    net_edge_bps: float
    execution_probability: float  # P(les deux jambes remplies)
    partial_execution_probability: float  # P(exactement une jambe remplie)
    execution_risk: ExecutionRisk
    pair_quality_score: float  # espérance nette après risque d'exécution, en bps
    decision: PairDecisionOutcome


def _categorize_execution_risk(execution_probability: float) -> ExecutionRisk:
    if execution_probability >= _EXECUTION_RISK_LOW_THRESHOLD:
        return ExecutionRisk.LOW
    if execution_probability >= _EXECUTION_RISK_MEDIUM_THRESHOLD:
        return ExecutionRisk.MEDIUM
    return ExecutionRisk.HIGH


def assess_pair_opportunity(
    funding_rate_bps: float,
    leg_a: LegAssessment,
    leg_b: LegAssessment,
    compensation_cost_estimate_bps: float,
) -> PairQualityAssessment:
    """Évalue une opportunité de paire (ADR-0021 §4.3).

    `compensation_cost_estimate_bps` : coût estimé (toujours positif, un
    coût, jamais un gain) si exactement une jambe se remplit et qu'il
    faut compenser - dépend du carnet au moment de l'évaluation, fourni
    par l'appelant (mesuré, pas une constante figée dans cette fonction).

    Hypothèse assumée et documentée (ADR-0021 §5, pas cachée) :
    indépendance des deux probabilités de remplissage - simplification
    de départ, à revisiter si des données réelles montrent une
    corrélation entre les deux marchés.
    """
    gross_edge_bps = abs(funding_rate_bps)
    fees_bps = leg_a.fee_bps + leg_b.fee_bps
    slippage_bps = leg_a.slippage_bps + leg_b.slippage_bps
    net_edge_bps = gross_edge_bps - fees_bps - slippage_bps

    execution_probability = leg_a.fill_probability * leg_b.fill_probability
    partial_execution_probability = (
        leg_a.fill_probability * (1 - leg_b.fill_probability)
        + (1 - leg_a.fill_probability) * leg_b.fill_probability
    )

    execution_risk = _categorize_execution_risk(execution_probability)

    pair_quality_score = (
        net_edge_bps * execution_probability - compensation_cost_estimate_bps * partial_execution_probability
    )

    decision = (
        PairDecisionOutcome.ACCEPT
        if pair_quality_score > MIN_PAIR_QUALITY_SCORE_BPS_BY_RISK[execution_risk]
        else PairDecisionOutcome.REJECT
    )

    return PairQualityAssessment(
        gross_edge_bps=gross_edge_bps,
        fees_bps=fees_bps,
        slippage_bps=slippage_bps,
        net_edge_bps=net_edge_bps,
        execution_probability=execution_probability,
        partial_execution_probability=partial_execution_probability,
        execution_risk=execution_risk,
        pair_quality_score=pair_quality_score,
        decision=decision,
    )
