"""Tests du moteur liquidation_cascade (chantier Liquidation Cascade, 16/08/2026)."""

from shared.decision_engine import Side
from strategies.liquidation_cascade import LiquidationCascadeAgent


def _features(**overrides):
    base = {
        "liquidation_cascade_intensity": 100_000.0,
        "momentum": -0.02,
        "spread_bps": 5.0,
    }
    base.update(overrides)
    return base


def test_negative_momentum_after_cascade_produces_buy_opinion():
    """Cascade de longs liquidés (prix en chute) -> pari sur le rebond -> ACHAT."""
    engine = LiquidationCascadeAgent()
    opinion = engine.evaluate(_features(momentum=-0.02))

    assert opinion is not None
    assert opinion.suggested_side == Side.BUY


def test_positive_momentum_after_cascade_produces_sell_opinion():
    """Cascade de courts liquidés (prix en hausse, short squeeze) -> VENTE."""
    engine = LiquidationCascadeAgent()
    opinion = engine.evaluate(_features(momentum=0.02))

    assert opinion is not None
    assert opinion.suggested_side == Side.SELL


def test_insufficient_liquidation_notional_produces_no_opinion():
    """Un mouvement de prix seul, sans liquidation notable, n'est pas une cascade."""
    engine = LiquidationCascadeAgent()
    opinion = engine.evaluate(_features(liquidation_cascade_intensity=100.0))
    assert opinion is None


def test_insufficient_momentum_produces_no_opinion():
    """Une liquidation notable seule, sans mouvement de prix notable, n'est pas une cascade."""
    engine = LiquidationCascadeAgent()
    opinion = engine.evaluate(_features(momentum=0.001))
    assert opinion is None


def test_excessive_spread_produces_no_opinion():
    engine = LiquidationCascadeAgent()
    opinion = engine.evaluate(_features(spread_bps=50.0))
    assert opinion is None


def test_zero_spread_produces_no_opinion():
    """Pas de mesure d'incertitude fiable à spread nul."""
    engine = LiquidationCascadeAgent()
    opinion = engine.evaluate(_features(spread_bps=0.0))
    assert opinion is None


def test_missing_liquidation_feature_produces_no_opinion():
    engine = LiquidationCascadeAgent()
    opinion = engine.evaluate({"momentum": -0.02, "spread_bps": 5.0})
    assert opinion is None


def test_missing_momentum_produces_no_opinion():
    engine = LiquidationCascadeAgent()
    opinion = engine.evaluate({"liquidation_cascade_intensity": 100_000.0, "spread_bps": 5.0})
    assert opinion is None


def test_score_never_exceeds_cap():
    engine = LiquidationCascadeAgent()
    opinion = engine.evaluate(_features(momentum=-0.50))  # mouvement extrême
    assert opinion.score <= 0.9


def test_confidence_is_deliberately_low_and_documented():
    """Moteur non calibré (aucune donnée réelle au 16/08/2026) - la
    confiance doit rester nettement plus basse que les moteurs
    directionnels déjà actifs (0.5-0.6 habituellement)."""
    engine = LiquidationCascadeAgent()
    opinion = engine.evaluate(_features())
    assert opinion.confidence == 0.4
    assert opinion.confidence < 0.5


def test_rationale_includes_both_signals_used():
    engine = LiquidationCascadeAgent()
    opinion = engine.evaluate(_features())
    assert "liquidation_cascade_intensity" in opinion.rationale
    assert "momentum" in opinion.rationale


def test_custom_parameters_override_defaults():
    engine = LiquidationCascadeAgent(parameters={"min_liquidation_notional_usd": 1_000_000.0})
    opinion = engine.evaluate(_features(liquidation_cascade_intensity=500_000.0))
    assert opinion is None  # sous le seuil personnalisé, même si au-dessus du défaut
