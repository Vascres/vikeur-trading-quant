"""Tests de la Phase 9 : features et registre d'immutabilité."""

import pytest

from feature_engine.features.momentum import Momentum
from feature_engine.features.order_flow_imbalance import OrderFlowImbalance
from feature_engine.features.spread import SpreadBps
from feature_engine.features.volatility import RealizedVolatility
from feature_engine.features.vwap import Vwap
from feature_engine.registry import compute_logic_hash


def test_spread_bps_basic_case():
    feature = SpreadBps()
    result = feature.compute({"best_bid": 100.0, "best_ask": 100.1})
    assert result == pytest.approx(9.995, rel=1e-3)


def test_spread_bps_missing_data_returns_none():
    feature = SpreadBps()
    assert feature.compute({"best_bid": 100.0}) is None


def test_order_flow_imbalance_buy_pressure():
    feature = OrderFlowImbalance()
    result = feature.compute({"bids": [[100, 10], [99, 5]], "asks": [[101, 3], [102, 2]]})
    # bid_volume=15, ask_volume=5 -> (15-5)/20 = 0.5
    assert result == pytest.approx(0.5)


def test_order_flow_imbalance_empty_book_returns_none():
    feature = OrderFlowImbalance()
    assert feature.compute({"bids": [], "asks": [[101, 3]]}) is None


def test_realized_volatility_constant_price_is_zero():
    feature = RealizedVolatility()
    closes = [100.0] * 22
    result = feature.compute({"closes": closes})
    assert result == pytest.approx(0.0, abs=1e-9)


def test_realized_volatility_insufficient_data_returns_none():
    feature = RealizedVolatility()
    assert feature.compute({"closes": [100.0, 101.0]}) is None


def test_realized_volatility_detects_variation():
    feature = RealizedVolatility()
    closes = [100.0, 102.0] * 11  # oscillation régulière
    result = feature.compute({"closes": closes})
    assert result is not None
    assert result > 0


def test_vwap_weighted_correctly():
    feature = Vwap()
    closes = [100.0] * 19 + [200.0]
    volumes = [1.0] * 19 + [1.0]
    result = feature.compute({"closes": closes, "volumes": volumes})
    expected = (100.0 * 19 + 200.0 * 1) / 20
    assert result == pytest.approx(expected)


def test_vwap_zero_volume_returns_none():
    feature = Vwap()
    closes = [100.0] * 20
    volumes = [0.0] * 20
    assert feature.compute({"closes": closes, "volumes": volumes}) is None


def test_momentum_positive_move():
    feature = Momentum()
    closes = [100.0] * 10 + [110.0]
    result = feature.compute({"closes": closes})
    assert result == pytest.approx(0.10)


def test_momentum_insufficient_data_returns_none():
    feature = Momentum()
    assert feature.compute({"closes": [100.0, 101.0]}) is None


def test_logic_hash_is_deterministic():
    feature = SpreadBps()
    assert compute_logic_hash(feature) == compute_logic_hash(feature)


def test_logic_hash_differs_between_distinct_features():
    assert compute_logic_hash(SpreadBps()) != compute_logic_hash(Momentum())
