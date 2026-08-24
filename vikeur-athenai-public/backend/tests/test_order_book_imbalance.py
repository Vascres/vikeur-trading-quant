"""Tests du moteur order_book_imbalance (ADR-0010)."""

from shared.decision_engine import Side
from strategies.order_book_imbalance import OrderBookImbalance


def _features(**overrides):
    base = {"order_flow_imbalance": 0.3, "spread_bps": 5.0}
    base.update(overrides)
    return base


def test_positive_imbalance_produces_buy_opinion():
    engine = OrderBookImbalance()
    opinion = engine.evaluate(_features(order_flow_imbalance=0.3))

    assert opinion is not None
    assert opinion.suggested_side == Side.BUY


def test_negative_imbalance_produces_sell_opinion():
    engine = OrderBookImbalance()
    opinion = engine.evaluate(_features(order_flow_imbalance=-0.3))

    assert opinion is not None
    assert opinion.suggested_side == Side.SELL


def test_weak_imbalance_produces_no_opinion():
    engine = OrderBookImbalance()
    opinion = engine.evaluate(_features(order_flow_imbalance=0.01))
    assert opinion is None


def test_excessive_spread_produces_no_opinion():
    engine = OrderBookImbalance()
    opinion = engine.evaluate(_features(spread_bps=50.0))
    assert opinion is None


def test_missing_feature_produces_no_opinion():
    engine = OrderBookImbalance()
    opinion = engine.evaluate({"order_flow_imbalance": 0.3})
    assert opinion is None


def test_uncertainty_derived_from_spread():
    engine = OrderBookImbalance()
    opinion = engine.evaluate(_features(spread_bps=10.0))
    assert opinion.uncertainty == 0.001


def test_score_never_exceeds_cap():
    engine = OrderBookImbalance()
    opinion = engine.evaluate(_features(order_flow_imbalance=0.99))
    assert opinion.score <= 0.85


def test_independent_from_momentum_engine_signal():
    """Ce moteur ne regarde jamais momentum, même absent des features -
    condition nécessaire pour que la fusion combine deux signaux
    réellement indépendants (ADR-0010)."""
    engine = OrderBookImbalance()
    opinion = engine.evaluate({"order_flow_imbalance": 0.3, "spread_bps": 5.0})
    assert opinion is not None
    assert "momentum" not in opinion.rationale
