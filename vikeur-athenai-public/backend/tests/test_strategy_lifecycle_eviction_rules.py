"""Tests de strategy_lifecycle.eviction_rules (Étape 3 du plan validé le 16/08/2026)."""

from __future__ import annotations

from decimal import Decimal


from strategy_lifecycle.eviction_rules import (
    determine_eviction_transition,
    determine_resurrection_transition,
)
from strategy_lifecycle.metrics import LifecycleMetrics
from strategy_lifecycle.states import (
    DEGRADED,
    EXPERIMENTAL,
    PRODUCTION,
    REGISTERED,
    SUSPENDED,
    UNDER_REVIEW,
    VALIDATED,
)


def _metrics(
    ev_net_bps=10.0, cumulative_pnl=Decimal("1.0"), profit_factor=1.5, sample_size=30
) -> LifecycleMetrics:
    return LifecycleMetrics(
        ev_net_bps=ev_net_bps,
        cumulative_pnl=cumulative_pnl,
        profit_factor=profit_factor,
        sample_size=sample_size,
    )


# --- Éviction : pas assez de données / statuts non éligibles ---


def test_no_transition_below_minimum_sample_size():
    """Mandat : "Nous ne devons pas suspendre une stratégie à cause de la
    variance normale" - une série de pertes sur peu de trades ne déclenche rien."""
    metrics = _metrics(ev_net_bps=-50.0, sample_size=5)
    assert determine_eviction_transition(EXPERIMENTAL, metrics, Decimal("350")) is None


def test_no_transition_for_registered_status():
    metrics = _metrics(ev_net_bps=-50.0, sample_size=100)
    assert determine_eviction_transition(REGISTERED, metrics, Decimal("350")) is None


def test_no_transition_for_suspended_status_via_eviction_path():
    """SUSPENDED ne se réévalue jamais via le chemin d'éviction - seule
    la résurrection peut le faire bouger."""
    metrics = _metrics(ev_net_bps=-50.0, sample_size=100)
    assert determine_eviction_transition(SUSPENDED, metrics, Decimal("350")) is None


# --- Éviction : drawdown -> DEGRADED immédiat ---


def test_severe_drawdown_skips_straight_to_degraded():
    """Mandat : "Si la somme cumulée des pertes... dépasse -5% du capital
    alloué -> Passage immédiat en DEGRADED" - saute UNDER_REVIEW."""
    metrics = _metrics(cumulative_pnl=Decimal("-8.75"), sample_size=30)  # -8.75 = -5% de 175
    result = determine_eviction_transition(EXPERIMENTAL, metrics, Decimal("175"))
    assert result is not None
    new_status, reason = result
    assert new_status == DEGRADED
    assert "8.75" in reason


def test_drawdown_below_threshold_does_not_trigger_degraded():
    metrics = _metrics(cumulative_pnl=Decimal("-5.00"), sample_size=30)  # -2.86% de 175, sous le seuil de 5%
    result = determine_eviction_transition(EXPERIMENTAL, metrics, Decimal("175"))
    assert result is None


def test_already_degraded_does_not_re_trigger_degraded():
    metrics = _metrics(cumulative_pnl=Decimal("-20.00"), sample_size=30)
    assert determine_eviction_transition(DEGRADED, metrics, Decimal("175")) is None


def test_zero_allocated_capital_never_divides_by_zero():
    metrics = _metrics(cumulative_pnl=Decimal("-5.00"), sample_size=30)
    # Ne doit jamais lever ZeroDivisionError - le drawdown est simplement ignoré
    # (le contrôle de l'espérance nette/profit factor reste opérant).
    result = determine_eviction_transition(EXPERIMENTAL, metrics, Decimal("0"))
    assert result is None or result[0] == UNDER_REVIEW


# --- Éviction : espérance nette négative / profit factor faible -> UNDER_REVIEW ---


def test_negative_ev_triggers_under_review():
    metrics = _metrics(ev_net_bps=-5.0, cumulative_pnl=Decimal("1.0"), profit_factor=1.5, sample_size=30)
    result = determine_eviction_transition(EXPERIMENTAL, metrics, Decimal("350"))
    assert result is not None
    assert result[0] == UNDER_REVIEW
    assert "espérance nette négative" in result[1]


def test_low_profit_factor_triggers_under_review():
    metrics = _metrics(ev_net_bps=5.0, cumulative_pnl=Decimal("1.0"), profit_factor=0.9, sample_size=30)
    result = determine_eviction_transition(PRODUCTION, metrics, Decimal("350"))
    assert result is not None
    assert result[0] == UNDER_REVIEW
    assert "profit factor" in result[1]


def test_healthy_metrics_trigger_no_transition():
    metrics = _metrics(ev_net_bps=15.0, cumulative_pnl=Decimal("5.0"), profit_factor=2.0, sample_size=30)
    assert determine_eviction_transition(VALIDATED, metrics, Decimal("350")) is None


def test_already_under_review_does_not_re_trigger_under_review():
    metrics = _metrics(ev_net_bps=-5.0, sample_size=30)
    assert determine_eviction_transition(UNDER_REVIEW, metrics, Decimal("350")) is None


def test_drawdown_takes_priority_over_ev_check_in_the_same_cycle():
    """Un seul palier de dégradation par cycle - le drawdown sévère
    l'emporte, pas un cumul UNDER_REVIEW puis DEGRADED dans le même appel."""
    metrics = _metrics(ev_net_bps=-5.0, cumulative_pnl=Decimal("-8.75"), sample_size=30)
    result = determine_eviction_transition(EXPERIMENTAL, metrics, Decimal("175"))
    assert result is not None
    assert result[0] == DEGRADED


# --- Résurrection ---


def test_resurrection_requires_minimum_quarantine_sample():
    metrics = _metrics(ev_net_bps=100.0, sample_size=10)
    assert determine_resurrection_transition(DEGRADED, metrics) is None


def test_resurrection_requires_ev_above_threshold():
    metrics = _metrics(ev_net_bps=20.0, sample_size=50)  # positif mais sous 40 bps
    assert determine_resurrection_transition(DEGRADED, metrics) is None


def test_resurrection_promotes_to_experimental_when_thresholds_met():
    metrics = _metrics(ev_net_bps=45.0, sample_size=50)
    result = determine_resurrection_transition(DEGRADED, metrics)
    assert result is not None
    assert result[0] == EXPERIMENTAL


def test_resurrection_not_evaluated_for_non_eligible_statuses():
    metrics = _metrics(ev_net_bps=100.0, sample_size=50)
    assert determine_resurrection_transition(EXPERIMENTAL, metrics) is None
    assert determine_resurrection_transition(UNDER_REVIEW, metrics) is None


def test_resurrection_works_for_suspended_too():
    metrics = _metrics(ev_net_bps=45.0, sample_size=50)
    result = determine_resurrection_transition(SUSPENDED, metrics)
    assert result is not None
    assert result[0] == EXPERIMENTAL
