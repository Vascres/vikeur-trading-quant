"""Tests de la Phase 11 : fonctions pures de seuillage et de fraîcheur.

evaluate_verdict prend des valeurs scalaires directes depuis ADR-0010
(plus de StrategyProposal, déprécié - cf. shared/decision_engine.py)."""

from datetime import UTC, datetime, timedelta

from decision_engine.thresholds import (
    BOOTSTRAP_THRESHOLDS,
    DECISION_THRESHOLDS,
    evaluate_bootstrap_verdict,
    evaluate_verdict,
    is_data_fresh,
    is_excluded_from_fusion,
)


def test_verdict_signal_when_all_thresholds_passed():
    assert evaluate_verdict(0.60, 0.005, 2.0) == "signal"


def test_verdict_no_signal_when_probability_too_low():
    assert evaluate_verdict(0.50, 0.005, 2.0) == "no_signal"


def test_verdict_no_signal_when_expected_value_not_positive():
    assert evaluate_verdict(0.60, 0.0, 2.0) == "no_signal"


def test_verdict_no_signal_when_risk_reward_too_low():
    assert evaluate_verdict(0.60, 0.005, 1.0) == "no_signal"


def test_verdict_respects_custom_thresholds():
    custom = {**DECISION_THRESHOLDS, "min_success_probability": 0.9}
    assert evaluate_verdict(0.60, 0.005, 2.0, custom) == "no_signal"


def test_data_fresh_within_window():
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    latest = now - timedelta(seconds=30)
    assert is_data_fresh(latest, now, max_age_seconds=120) is True


def test_data_not_fresh_outside_window():
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    latest = now - timedelta(seconds=200)
    assert is_data_fresh(latest, now, max_age_seconds=120) is False


def test_data_fresh_boundary_is_inclusive():
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    latest = now - timedelta(seconds=120)
    assert is_data_fresh(latest, now, max_age_seconds=120) is True


# --- ADR-0014 : evaluate_bootstrap_verdict (mode paper, calibration 'collecting') ---


def test_bootstrap_verdict_signal_when_all_thresholds_passed():
    assert evaluate_bootstrap_verdict(0.80, 0.005, 2.0) == "signal"


def test_bootstrap_verdict_no_signal_when_score_too_low():
    assert evaluate_bootstrap_verdict(0.70, 0.005, 2.0) == "no_signal"


def test_bootstrap_verdict_no_signal_when_expected_value_not_positive():
    assert evaluate_bootstrap_verdict(0.80, 0.0, 2.0) == "no_signal"


def test_bootstrap_verdict_no_signal_when_risk_reward_too_low():
    assert evaluate_bootstrap_verdict(0.80, 0.005, 1.0) == "no_signal"


def test_bootstrap_threshold_stricter_than_calibrated_probability_threshold():
    """ADR-0014 : le seuil de score brut doit être plus exigeant que le
    seuil de probabilité calibrée (0.55) - compense l'absence de toute
    validation statistique en mode démarrage."""
    assert BOOTSTRAP_THRESHOLDS["min_fused_score"] > DECISION_THRESHOLDS["min_success_probability"]


# --- Étape 3 (16/08/2026) : is_excluded_from_fusion ---


def test_unknown_status_never_excluded_in_paper():
    """Comportement historique préservé : aucune ligne de lifecycle
    encore initialisée -> pas d'exclusion en paper."""
    assert is_excluded_from_fusion(None, "paper") is False


def test_unknown_status_excluded_in_real():
    """Aucune preuve de rentabilité disponible -> jamais en réel."""
    assert is_excluded_from_fusion(None, "real") is True


def test_registered_and_collecting_always_excluded():
    assert is_excluded_from_fusion("registered", "paper") is True
    assert is_excluded_from_fusion("registered", "real") is True
    assert is_excluded_from_fusion("collecting", "paper") is True
    assert is_excluded_from_fusion("collecting", "real") is True


def test_suspended_and_deprecated_always_excluded():
    assert is_excluded_from_fusion("suspended", "paper") is True
    assert is_excluded_from_fusion("suspended", "real") is True
    assert is_excluded_from_fusion("deprecated", "paper") is True
    assert is_excluded_from_fusion("deprecated", "real") is True


def test_degraded_continues_trading_in_paper_but_not_real():
    """Mandat : "elle continue de tourner en Paper pour voir si elle se rétablit"."""
    assert is_excluded_from_fusion("degraded", "paper") is False
    assert is_excluded_from_fusion("degraded", "real") is True


def test_experimental_is_paper_only_by_definition():
    assert is_excluded_from_fusion("experimental", "paper") is False
    assert is_excluded_from_fusion("experimental", "real") is True


def test_validated_production_under_review_never_excluded():
    for status in ("validated", "production", "under_review"):
        assert is_excluded_from_fusion(status, "paper") is False
        assert is_excluded_from_fusion(status, "real") is False
