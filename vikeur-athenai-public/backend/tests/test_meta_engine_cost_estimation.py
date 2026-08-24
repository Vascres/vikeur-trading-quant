"""Tests de meta_engine.cost_estimation (ADR-0010) - relocalisation des
formules de l'ancienne stratégie unique, sans changement de comportement."""

import pytest

from meta_engine.cost_estimation import (
    compute_funding_impact_bps,
    estimate_expected_value,
    estimate_risk_reward_ratio,
    evaluate_costs,
)


def test_expected_value_subtracts_spread_cost():
    features = {"momentum": 0.02, "spread_bps": 10.0}
    assert estimate_expected_value(features) == pytest.approx(0.02 - 0.001)


def test_expected_value_none_when_momentum_missing():
    assert estimate_expected_value({"spread_bps": 10.0}) is None


def test_expected_value_none_when_spread_missing():
    assert estimate_expected_value({"momentum": 0.02}) is None


# --- ADR-0016 : nettage des frais réels mesurés ---


def test_expected_value_defaults_to_no_fee_deduction_for_backward_compatibility():
    """Aucun appelant existant (avant ADR-0016) ne fournit encore de frais -
    le comportement par défaut doit rester strictement identique."""
    features = {"momentum": 0.02, "spread_bps": 10.0}
    assert estimate_expected_value(features) == estimate_expected_value(features, round_trip_fee_bps=0.0)


def test_expected_value_nets_round_trip_fee_bps():
    features = {"momentum": 0.02, "spread_bps": 10.0}
    # 0.02 - (10 bps de spread) - (40 bps de frais round-trip, ex. palier HTX de base)
    result = estimate_expected_value(features, round_trip_fee_bps=40.0)
    assert result == pytest.approx(0.02 - 0.001 - 0.004)


def test_expected_value_can_become_negative_once_fees_are_netted():
    """Cas exact diagnostiqué le 1er août : un edge brut de quelques bps ne
    couvre pas un coût round-trip réel de 40 bps."""
    features = {"momentum": 0.0004, "spread_bps": 1.0}  # edge brut ~4 bps
    result = estimate_expected_value(features, round_trip_fee_bps=40.0)
    assert result is not None
    assert result < 0


def test_risk_reward_ratio_divides_momentum_by_volatility():
    features = {"momentum": 0.02, "realized_volatility": 0.01}
    assert estimate_risk_reward_ratio(features) == pytest.approx(2.0)


def test_risk_reward_ratio_none_when_volatility_zero():
    features = {"momentum": 0.02, "realized_volatility": 0.0}
    assert estimate_risk_reward_ratio(features) is None


def test_risk_reward_ratio_none_when_volatility_negative():
    features = {"momentum": 0.02, "realized_volatility": -0.01}
    assert estimate_risk_reward_ratio(features) is None


def test_risk_reward_ratio_none_when_features_missing():
    assert estimate_risk_reward_ratio({}) is None


# --- Chantier CostModel unique (16/08/2026) : evaluate_costs / compute_funding_impact_bps ---


def test_evaluate_costs_matches_previous_ad_hoc_calculation():
    """Non-régression : `estimate_expected_value` délègue désormais à
    `evaluate_costs` en interne - le résultat doit rester identique, bit
    pour bit près, aux valeurs de référence déjà couvertes plus haut."""
    features = {"momentum": 0.02, "spread_bps": 10.0}
    evaluation = evaluate_costs(raw_edge_bps=200.0, spread_bps=10.0, round_trip_fee_bps=40.0)
    assert evaluation.net_edge_bps / 10_000 == pytest.approx(
        estimate_expected_value(features, round_trip_fee_bps=40.0)
    )


def test_evaluate_costs_breaks_down_every_component_separately():
    evaluation = evaluate_costs(raw_edge_bps=100.0, spread_bps=10.0, round_trip_fee_bps=40.0)
    assert evaluation.raw_edge_bps == 100.0
    assert evaluation.spread_bps == 10.0
    assert evaluation.fee_bps == 40.0
    assert evaluation.funding_impact_bps == 0.0
    assert evaluation.net_edge_bps == pytest.approx(50.0)
    assert evaluation.cleared_costs is True


def test_evaluate_costs_cleared_false_when_net_edge_not_strictly_positive():
    evaluation = evaluate_costs(raw_edge_bps=40.0, spread_bps=10.0, round_trip_fee_bps=30.0)
    assert evaluation.net_edge_bps == pytest.approx(0.0)
    assert evaluation.cleared_costs is False  # strictement positif requis, pas >=0


def test_evaluate_costs_ignores_funding_when_holding_period_is_zero():
    """Défaut neutre - aucun impact funding tant qu'aucune durée de
    détention n'est explicitement fournie (comportement des 3 moteurs
    directionnels actifs aujourd'hui, qui n'en fournissent aucune)."""
    evaluation = evaluate_costs(raw_edge_bps=100.0, round_trip_fee_bps=40.0, funding_rate_bps=5.0)
    assert evaluation.funding_impact_bps == 0.0


def test_compute_funding_impact_bps_scales_with_holding_period_not_a_single_period():
    """Le cas précis corrigé par l'audit du 16/08/2026 (ADR-0021) : le
    funding s'accumule sur plusieurs règlements couverts par la durée de
    détention, jamais une seule période comparée à un coût complet."""
    one_period = compute_funding_impact_bps(
        funding_rate_bps=1.0, expected_holding_period_hours=8.0, direction_sign=1
    )
    three_periods = compute_funding_impact_bps(
        funding_rate_bps=1.0, expected_holding_period_hours=24.0, direction_sign=1
    )
    assert one_period == pytest.approx(1.0)
    assert three_periods == pytest.approx(3.0)  # 24h / 8h par règlement = 3 règlements


def test_compute_funding_impact_bps_sign_reflects_who_pays_whom():
    received = compute_funding_impact_bps(
        funding_rate_bps=2.0, expected_holding_period_hours=8.0, direction_sign=1
    )
    paid = compute_funding_impact_bps(
        funding_rate_bps=2.0, expected_holding_period_hours=8.0, direction_sign=-1
    )
    assert received == pytest.approx(2.0)
    assert paid == pytest.approx(-2.0)


def test_evaluate_costs_with_funding_can_turn_a_negative_edge_positive():
    """Illustration directe du correctif : un edge d'ouverture négatif
    (coût > funding d'une seule période) peut redevenir positif une fois
    plusieurs règlements pris en compte sur une détention plus longue."""
    single_period = evaluate_costs(
        raw_edge_bps=0.0,
        round_trip_fee_bps=52.0,
        funding_rate_bps=1.0,
        expected_holding_period_hours=8.0,
        funding_direction_sign=1,
    )
    multi_day = evaluate_costs(
        raw_edge_bps=0.0,
        round_trip_fee_bps=52.0,
        funding_rate_bps=1.0,
        expected_holding_period_hours=18
        * 24.0,  # ~18 jours (> seuil de rentabilité de ~17,3j, audit du 16/08)
        funding_direction_sign=1,
    )
    assert single_period.cleared_costs is False
    assert multi_day.cleared_costs is True
