"""Tests de strategies.cross_sectional_momentum.CrossSectionalMomentum (ADR-0017)."""

from __future__ import annotations

from shared.decision_engine import Side
from strategies.cross_sectional_momentum import CrossSectionalMomentum


def _features(**overrides) -> dict:
    defaults = {
        "cross_sectional_rank": 1.0,
        "cross_sectional_spread": 0.01,  # > min_spread_threshold par défaut (0.002)
        "realized_volatility": 0.02,
    }
    defaults.update(overrides)
    return defaults


def test_leader_produces_buy_opinion():
    opinion = CrossSectionalMomentum().evaluate(_features(cross_sectional_rank=1.0))
    assert opinion is not None
    assert opinion.suggested_side == Side.BUY


def test_laggard_produces_sell_opinion():
    opinion = CrossSectionalMomentum().evaluate(_features(cross_sectional_rank=-1.0))
    assert opinion is not None
    assert opinion.suggested_side == Side.SELL


def test_middle_rank_produces_no_opinion():
    opinion = CrossSectionalMomentum().evaluate(_features(cross_sectional_rank=0.0))
    assert opinion is None


def test_spread_below_threshold_produces_no_opinion():
    """Dispersion trop faible entre symboles - classement non significatif,
    même si un rang leader/retardataire a techniquement été assigné."""
    opinion = CrossSectionalMomentum().evaluate(_features(cross_sectional_spread=0.0005))
    assert opinion is None


def test_missing_rank_produces_no_opinion():
    features = _features()
    del features["cross_sectional_rank"]
    assert CrossSectionalMomentum().evaluate(features) is None


def test_missing_spread_produces_no_opinion():
    features = _features()
    del features["cross_sectional_spread"]
    assert CrossSectionalMomentum().evaluate(features) is None


def test_missing_volatility_produces_no_opinion():
    features = _features()
    del features["realized_volatility"]
    assert CrossSectionalMomentum().evaluate(features) is None


def test_zero_volatility_produces_no_opinion():
    opinion = CrossSectionalMomentum().evaluate(_features(realized_volatility=0.0))
    assert opinion is None


def test_confidence_increases_with_spread_up_to_max():
    weak = CrossSectionalMomentum().evaluate(_features(cross_sectional_spread=0.003))
    strong = CrossSectionalMomentum().evaluate(_features(cross_sectional_spread=0.05))

    assert weak is not None
    assert strong is not None
    assert strong.confidence > weak.confidence
    assert strong.confidence <= CrossSectionalMomentum().parameters["max_confidence"]


def test_rationale_contains_the_features_used():
    opinion = CrossSectionalMomentum().evaluate(_features())
    assert opinion is not None
    assert set(opinion.rationale) == {"cross_sectional_rank", "cross_sectional_spread", "realized_volatility"}


def test_uncertainty_equals_realized_volatility():
    opinion = CrossSectionalMomentum().evaluate(_features(realized_volatility=0.037))
    assert opinion is not None
    assert opinion.uncertainty == 0.037


def test_custom_parameters_override_defaults():
    engine = CrossSectionalMomentum(parameters={"min_spread_threshold": 0.5})
    # Une dispersion normalement suffisante (0.01) ne l'est plus avec un seuil personnalisé à 0.5.
    assert engine.evaluate(_features(cross_sectional_spread=0.01)) is None
