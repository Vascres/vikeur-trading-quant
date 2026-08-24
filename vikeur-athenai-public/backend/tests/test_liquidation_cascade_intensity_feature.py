"""Tests de LiquidationCascadeIntensity (chantier Liquidation Cascade, 16/08/2026)."""

from feature_engine.features.liquidation_cascade_intensity import LiquidationCascadeIntensity


def test_sums_notionals_in_the_provided_window():
    feature = LiquidationCascadeIntensity()
    value = feature.compute({"recent_liquidation_notionals": [1000.0, 2500.0, 500.0]})
    assert value == 4000.0


def test_empty_window_returns_zero_not_none():
    """Aucune liquidation sur la fenêtre est un résultat normal (y
    compris sur un exchange sans flux collecté, comme HTX aujourd'hui) -
    jamais confondu avec une donnée manquante."""
    feature = LiquidationCascadeIntensity()
    value = feature.compute({"recent_liquidation_notionals": []})
    assert value == 0.0


def test_missing_key_returns_none():
    """Distinct du cas ci-dessus : l'appelant n'a jamais fourni la
    donnée du tout (pas encore branché) - None, pas 0.0."""
    feature = LiquidationCascadeIntensity()
    value = feature.compute({})
    assert value is None
