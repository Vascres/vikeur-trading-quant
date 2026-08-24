"""Tests de pair_execution.state_machine (ADR-0021 §4.5-§4.6) - le cœur
de la demande : la gestion explicite de l'exécution partielle, pas une
simple règle "les deux ordres doivent réussir"."""

from __future__ import annotations

from pair_execution.state_machine import (
    BLOCKING_STATUSES,
    LegOutcome,
    PairStatus,
    ResolutionAction,
    build_incident_record,
    decide_completion_attempt,
    determine_execution_outcome,
    is_symbol_blocked_by_unresolved_pair,
)


# --- determine_execution_outcome ---


def test_both_legs_filled_is_both_filled():
    assert determine_execution_outcome(LegOutcome.FILLED, LegOutcome.FILLED) == PairStatus.BOTH_FILLED


def test_both_legs_rejected_is_both_rejected():
    assert determine_execution_outcome(LegOutcome.REJECTED, LegOutcome.REJECTED) == PairStatus.BOTH_REJECTED


def test_leg_a_filled_leg_b_rejected_is_partial_execution():
    assert determine_execution_outcome(LegOutcome.FILLED, LegOutcome.REJECTED) == PairStatus.PARTIAL_EXECUTION


def test_leg_a_rejected_leg_b_filled_is_partial_execution():
    assert determine_execution_outcome(LegOutcome.REJECTED, LegOutcome.FILLED) == PairStatus.PARTIAL_EXECUTION


# --- decide_completion_attempt ---


def test_completion_attempted_when_edge_still_acceptable():
    decision = decide_completion_attempt(
        current_net_edge_bps=18.0,
        original_net_edge_bps=19.0,
        max_edge_degradation_bps=5.0,
        attempts_made=0,
        max_attempts=3,
    )
    assert decision.should_attempt is True


def test_completion_refused_when_edge_degraded_beyond_threshold():
    """Jamais un renvoi aveugle du même ordre - si le marché a trop
    bougé, la compensation est préférée à une complétion forcée."""
    decision = decide_completion_attempt(
        current_net_edge_bps=-10.0,
        original_net_edge_bps=19.0,
        max_edge_degradation_bps=5.0,
        attempts_made=0,
        max_attempts=3,
    )
    assert decision.should_attempt is False
    assert "dégradé" in decision.reason


def test_completion_refused_after_max_attempts_reached():
    decision = decide_completion_attempt(
        current_net_edge_bps=19.0,  # edge inchangé, aurait été acceptable
        original_net_edge_bps=19.0,
        max_edge_degradation_bps=5.0,
        attempts_made=3,
        max_attempts=3,
    )
    assert decision.should_attempt is False
    assert "tentatives" in decision.reason


def test_edge_degradation_exactly_at_threshold_is_still_accepted():
    decision = decide_completion_attempt(
        current_net_edge_bps=14.0,
        original_net_edge_bps=19.0,  # dégradation de 5.0, exactement le seuil
        max_edge_degradation_bps=5.0,
        attempts_made=0,
        max_attempts=3,
    )
    assert decision.should_attempt is True


# --- is_symbol_blocked_by_unresolved_pair (§4.6) ---


def test_symbol_not_blocked_when_no_pair_in_flight():
    assert is_symbol_blocked_by_unresolved_pair([]) is False


def test_symbol_not_blocked_by_a_cleanly_resolved_pair():
    assert is_symbol_blocked_by_unresolved_pair([PairStatus.BOTH_FILLED, PairStatus.RESOLVED]) is False


def test_symbol_blocked_while_partial_execution_unresolved():
    assert is_symbol_blocked_by_unresolved_pair([PairStatus.PARTIAL_EXECUTION]) is True


def test_symbol_blocked_while_completing_missing_leg():
    assert is_symbol_blocked_by_unresolved_pair([PairStatus.COMPLETING_MISSING_LEG]) is True


def test_symbol_blocked_while_compensating():
    assert is_symbol_blocked_by_unresolved_pair([PairStatus.COMPENSATING]) is True


def test_every_blocking_status_actually_blocks():
    """Vérifie qu'aucun état de la liste officielle de blocage n'a été
    oublié dans la logique - si BLOCKING_STATUSES change un jour, ce
    test échoue tant que la fonction n'est pas mise à jour en conséquence."""
    for status in BLOCKING_STATUSES:
        assert is_symbol_blocked_by_unresolved_pair([status]) is True


# --- build_incident_record ---


def test_incident_record_captures_the_essential_facts():
    record = build_incident_record(
        filled_leg_market_type="spot",
        missing_leg_market_type="futures_perpetual",
        residual_exposure_notional=125.50,
        resolution_action=ResolutionAction.COMPENSATED_OPEN_LEG,
        realized_cost_bps=3.2,
    )
    assert record.filled_leg == "spot"
    assert record.missing_leg == "futures_perpetual"
    assert record.residual_exposure_notional == 125.50
    assert record.resolution_action == ResolutionAction.COMPENSATED_OPEN_LEG
    assert record.realized_cost_bps == 3.2


def test_incident_record_allows_unresolved_cost_to_be_none():
    """Tant que l'incident n'est pas résolu, le coût réel n'est pas
    encore connu - jamais un zéro inventé à la place d'une valeur
    manquante."""
    record = build_incident_record(
        filled_leg_market_type="futures_perpetual",
        missing_leg_market_type="spot",
        residual_exposure_notional=80.0,
        resolution_action=ResolutionAction.UNRESOLVED,
    )
    assert record.realized_cost_bps is None
