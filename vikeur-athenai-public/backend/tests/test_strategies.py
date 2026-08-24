"""Tests du moteur de référence momentum_imbalance_threshold (Phase 10 ;
migré vers DecisionEngine par ADR-0010) et du registre d'immutabilité."""

from shared.decision_engine import Side
from strategies.momentum_imbalance_threshold import MomentumImbalanceThreshold
from strategies.registry import compute_logic_hash


def _features(**overrides):
    base = {
        "momentum": 0.01,
        "order_flow_imbalance": 0.3,
        "spread_bps": 5.0,
        "realized_volatility": 0.005,
    }
    base.update(overrides)
    return base


def test_aligned_bullish_signal_produces_buy_opinion():
    engine = MomentumImbalanceThreshold()
    opinion = engine.evaluate(_features(momentum=0.01, order_flow_imbalance=0.3))

    assert opinion is not None
    assert opinion.suggested_side == Side.BUY
    assert 0.5 < opinion.score <= 0.9


def test_aligned_bearish_signal_produces_sell_opinion():
    engine = MomentumImbalanceThreshold()
    opinion = engine.evaluate(_features(momentum=-0.01, order_flow_imbalance=-0.3))

    assert opinion is not None
    assert opinion.suggested_side == Side.SELL


def test_conflicting_signals_produce_no_opinion():
    engine = MomentumImbalanceThreshold()
    opinion = engine.evaluate(_features(momentum=0.01, order_flow_imbalance=-0.3))
    assert opinion is None


def test_weak_momentum_produces_no_opinion():
    engine = MomentumImbalanceThreshold()
    opinion = engine.evaluate(_features(momentum=0.0001))
    assert opinion is None


def test_excessive_spread_produces_no_opinion():
    engine = MomentumImbalanceThreshold()
    opinion = engine.evaluate(_features(spread_bps=50.0))
    assert opinion is None


def test_zero_volatility_produces_no_opinion():
    engine = MomentumImbalanceThreshold()
    opinion = engine.evaluate(_features(realized_volatility=0.0))
    assert opinion is None


def test_missing_feature_produces_no_opinion():
    engine = MomentumImbalanceThreshold()
    opinion = engine.evaluate({"momentum": 0.01})
    assert opinion is None


def test_score_never_exceeds_cap():
    engine = MomentumImbalanceThreshold()
    opinion = engine.evaluate(_features(momentum=0.5, order_flow_imbalance=0.9))
    assert opinion.score <= 0.9


def test_uncertainty_equals_volatility():
    engine = MomentumImbalanceThreshold()
    opinion = engine.evaluate(_features(realized_volatility=0.0123))
    assert opinion.uncertainty == 0.0123


def test_confidence_is_fixed_documented_value():
    engine = MomentumImbalanceThreshold()
    opinion = engine.evaluate(_features())
    assert opinion.confidence == engine.parameters["confidence"]


def test_rationale_contains_all_features_used():
    engine = MomentumImbalanceThreshold()
    opinion = engine.evaluate(_features())
    assert set(opinion.rationale.keys()) == {
        "momentum",
        "order_flow_imbalance",
        "spread_bps",
        "realized_volatility",
    }


def test_logic_hash_is_deterministic():
    engine = MomentumImbalanceThreshold()
    assert compute_logic_hash(engine) == compute_logic_hash(engine)
