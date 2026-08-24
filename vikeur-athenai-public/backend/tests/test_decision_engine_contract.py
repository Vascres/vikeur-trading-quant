"""Tests du contrat DecisionEngine (ADR-0002, ADR-0011)."""

from shared.decision_engine import EngineMetadata


def test_allowed_regimes_defaults_to_empty_frozenset():
    metadata = EngineMetadata(name="test_engine", version=1, description="test")
    assert metadata.allowed_regimes == frozenset()


def test_allowed_regimes_can_be_restricted():
    metadata = EngineMetadata(
        name="test_engine",
        version=1,
        description="test",
        allowed_regimes=frozenset({"bullish_high_volatility"}),
    )
    assert "bullish_high_volatility" in metadata.allowed_regimes
    assert "bearish_low_volatility" not in metadata.allowed_regimes


# --- Chantier de routage par market_type (16/08/2026) ---


def test_market_type_defaults_to_spot():
    """Comportement inchangé pour les 3 moteurs directionnels déjà actifs -
    aucun n'a été modifié pour déclarer un market_type explicite."""
    metadata = EngineMetadata(name="test_engine", version=1, description="test")
    assert metadata.market_type == "spot"


def test_market_type_can_be_declared_futures():
    metadata = EngineMetadata(
        name="liquidation_cascade", version=1, description="test", market_type="futures_perpetual"
    )
    assert metadata.market_type == "futures_perpetual"
