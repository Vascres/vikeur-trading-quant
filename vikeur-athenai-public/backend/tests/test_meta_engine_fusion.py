"""Tests de meta_engine.fusion.fuse_opinions (ADR-0010)."""

from meta_engine.fusion import fuse_opinions
from shared.decision_engine import EngineOpinion, Side


def _opinion(side: Side, score: float, confidence: float) -> EngineOpinion:
    return EngineOpinion(suggested_side=side, score=score, confidence=confidence, uncertainty=0.01)


def test_no_opinions_returns_no_side():
    result = fuse_opinions([], [])
    assert result.suggested_side is None
    assert result.fused_score is None


def test_single_opinion_wins_by_default():
    opinion = _opinion(Side.BUY, score=0.7, confidence=0.6)
    result = fuse_opinions([opinion], ["engine_a"])

    assert result.suggested_side == Side.BUY
    assert result.fused_score == 0.7
    assert result.contributing_engine_names == ["engine_a"]


def test_agreeing_opinions_produce_confidence_weighted_average():
    opinion_a = _opinion(Side.BUY, score=0.8, confidence=0.6)
    opinion_b = _opinion(Side.BUY, score=0.6, confidence=0.4)
    result = fuse_opinions([opinion_a, opinion_b], ["engine_a", "engine_b"])

    expected = (0.6 * 0.8 + 0.4 * 0.6) / (0.6 + 0.4)
    assert result.suggested_side == Side.BUY
    assert result.fused_score == expected
    assert set(result.contributing_engine_names) == {"engine_a", "engine_b"}


def test_disagreeing_opinions_pick_higher_weighted_side():
    strong_buy = _opinion(Side.BUY, score=0.9, confidence=0.8)
    weak_sell = _opinion(Side.SELL, score=0.5, confidence=0.3)
    result = fuse_opinions([strong_buy, weak_sell], ["engine_a", "engine_b"])

    assert result.suggested_side == Side.BUY
    assert result.contributing_engine_names == ["engine_a"]


def test_exact_tie_between_sides_produces_no_side():
    buy = _opinion(Side.BUY, score=0.7, confidence=0.5)
    sell = _opinion(Side.SELL, score=0.7, confidence=0.5)
    result = fuse_opinions([buy, sell], ["engine_a", "engine_b"])

    assert result.suggested_side is None
    assert result.fused_score is None


def test_weights_applied_reflects_confidence_of_winning_side_only():
    buy = _opinion(Side.BUY, score=0.7, confidence=0.6)
    sell = _opinion(Side.SELL, score=0.4, confidence=0.2)
    result = fuse_opinions([buy, sell], ["engine_a", "engine_b"])

    assert result.weights_applied == {"engine_a": 0.6}
