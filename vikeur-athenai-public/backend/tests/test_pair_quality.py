"""Tests de pair_execution.pair_quality (ADR-0021).

Inclut les deux exemples exacts donnés lors de la conception (BTC
accepté, SOL rejeté) pour vérifier que la formule produit bien le
comportement attendu, pas seulement des cas synthétiques.
"""

from __future__ import annotations

from pair_execution.pair_quality import (
    ExecutionRisk,
    LegAssessment,
    PairDecisionOutcome,
    assess_pair_opportunity,
)


def test_btc_example_from_conception_is_accepted():
    """BTC Spot/Futures : gross 0.42%, fees 0.16%, slippage 0.07%,
    net 0.19%, probabilité 98.7%, risque LOW -> ACCEPT."""
    leg_spot = LegAssessment(market_type="spot", fee_bps=8.0, slippage_bps=3.0, fill_probability=0.994)
    leg_futures = LegAssessment(
        market_type="futures_perpetual", fee_bps=8.0, slippage_bps=4.0, fill_probability=0.993
    )

    result = assess_pair_opportunity(
        funding_rate_bps=42.0,  # 0.42%
        leg_a=leg_spot,
        leg_b=leg_futures,
        compensation_cost_estimate_bps=15.0,
    )

    assert result.gross_edge_bps == 42.0
    assert result.fees_bps == 16.0
    assert result.execution_risk == ExecutionRisk.LOW
    assert result.decision == PairDecisionOutcome.ACCEPT
    assert result.pair_quality_score > 0


def test_sol_example_from_conception_is_rejected():
    """SOL Spot/Futures : gross 0.55%, net 0.28%, probabilité 81.2%,
    risque HIGH -> REJECT malgré une espérance nette positive (~15.5 bps) -
    exactement le cas qui a révélé le besoin d'une marge de sécurité
    croissante avec le risque (une EV positive mais faible ne suffit pas
    quand le risque d'exécution est HIGH, cf. MIN_PAIR_QUALITY_SCORE_BPS_BY_RISK)."""
    leg_spot = LegAssessment(market_type="spot", fee_bps=8.0, slippage_bps=5.0, fill_probability=0.95)
    leg_futures = LegAssessment(
        market_type="futures_perpetual", fee_bps=8.0, slippage_bps=6.0, fill_probability=0.855
    )

    result = assess_pair_opportunity(
        funding_rate_bps=55.0,  # 0.55%
        leg_a=leg_spot,
        leg_b=leg_futures,
        compensation_cost_estimate_bps=40.0,
    )

    assert result.net_edge_bps > 0  # l'edge net "brut" est bien positif...
    assert result.execution_risk == ExecutionRisk.HIGH
    assert result.pair_quality_score > 0  # ...l'espérance ajustée aussi...
    assert (
        result.decision == PairDecisionOutcome.REJECT
    )  # ...mais rejeté : marge insuffisante pour du risque HIGH


def test_high_risk_opportunity_needs_a_larger_margin_than_low_risk():
    """Le garde-fou central de §4.3 : une espérance nette positive mais
    faible n'est acceptée que si le risque d'exécution est faible - la
    même espérance sur une paire à risque élevé doit être rejetée."""

    def leg(p):
        return LegAssessment(market_type="spot", fee_bps=1.0, slippage_bps=1.0, fill_probability=p)

    # Risque LOW (0.99*0.99=0.9801) : une petite espérance positive suffit.
    low_risk = assess_pair_opportunity(10.0, leg(0.99), leg(0.99), compensation_cost_estimate_bps=1.0)
    assert low_risk.execution_risk == ExecutionRisk.LOW
    assert low_risk.decision == PairDecisionOutcome.ACCEPT

    # Risque HIGH (0.5*0.5=0.25) avec la même espérance nette brute :
    # la marge de sécurité de 20 bps exigée pour HIGH doit rejeter.
    high_risk = assess_pair_opportunity(10.0, leg(0.5), leg(0.5), compensation_cost_estimate_bps=1.0)
    assert high_risk.execution_risk == ExecutionRisk.HIGH
    assert high_risk.decision == PairDecisionOutcome.REJECT


def test_negative_net_edge_is_always_rejected_regardless_of_execution_probability():
    leg = LegAssessment(market_type="spot", fee_bps=50.0, slippage_bps=50.0, fill_probability=1.0)
    result = assess_pair_opportunity(
        funding_rate_bps=10.0, leg_a=leg, leg_b=leg, compensation_cost_estimate_bps=0.0
    )
    assert result.net_edge_bps < 0
    assert result.decision == PairDecisionOutcome.REJECT


def test_execution_probability_is_product_of_both_legs():
    leg_a = LegAssessment(market_type="spot", fee_bps=0.0, slippage_bps=0.0, fill_probability=0.9)
    leg_b = LegAssessment(
        market_type="futures_perpetual", fee_bps=0.0, slippage_bps=0.0, fill_probability=0.8
    )
    result = assess_pair_opportunity(
        funding_rate_bps=100.0, leg_a=leg_a, leg_b=leg_b, compensation_cost_estimate_bps=0.0
    )
    assert result.execution_probability == 0.9 * 0.8


def test_partial_execution_probability_matches_expected_formula():
    leg_a = LegAssessment(market_type="spot", fee_bps=0.0, slippage_bps=0.0, fill_probability=0.9)
    leg_b = LegAssessment(
        market_type="futures_perpetual", fee_bps=0.0, slippage_bps=0.0, fill_probability=0.8
    )
    result = assess_pair_opportunity(
        funding_rate_bps=100.0, leg_a=leg_a, leg_b=leg_b, compensation_cost_estimate_bps=0.0
    )
    expected = 0.9 * (1 - 0.8) + (1 - 0.9) * 0.8
    assert result.partial_execution_probability == expected


def test_execution_risk_categorization_thresholds():
    def leg(p):
        return LegAssessment(market_type="spot", fee_bps=0.0, slippage_bps=0.0, fill_probability=p)

    # 0.99 * 0.99 = 0.9801 >= 0.95 -> LOW
    r_low = assess_pair_opportunity(100.0, leg(0.99), leg(0.99), 0.0)
    assert r_low.execution_risk == ExecutionRisk.LOW

    # 0.95 * 0.95 = 0.9025 -> MEDIUM (>= 0.85, < 0.95)
    r_medium = assess_pair_opportunity(100.0, leg(0.95), leg(0.95), 0.0)
    assert r_medium.execution_risk == ExecutionRisk.MEDIUM

    # 0.5 * 0.5 = 0.25 -> HIGH
    r_high = assess_pair_opportunity(100.0, leg(0.5), leg(0.5), 0.0)
    assert r_high.execution_risk == ExecutionRisk.HIGH


def test_higher_compensation_cost_can_flip_accept_to_reject():
    leg = LegAssessment(market_type="spot", fee_bps=5.0, slippage_bps=5.0, fill_probability=0.85)
    cheap_compensation = assess_pair_opportunity(50.0, leg, leg, compensation_cost_estimate_bps=1.0)
    expensive_compensation = assess_pair_opportunity(50.0, leg, leg, compensation_cost_estimate_bps=500.0)

    assert cheap_compensation.decision == PairDecisionOutcome.ACCEPT
    assert expensive_compensation.decision == PairDecisionOutcome.REJECT
