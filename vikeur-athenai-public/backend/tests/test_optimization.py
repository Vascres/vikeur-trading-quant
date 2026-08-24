from optimization.capital_allocator import compute_allocation_fractions
from optimization.performance_evaluator import compute_strategy_score, meets_deactivation_criteria


def test_compute_strategy_score_reuses_expectancy():
    assert compute_strategy_score([10, -5, 20, -5]) == 5.0


def test_meets_deactivation_criteria_false_below_min_trades():
    assert meets_deactivation_criteria(score=-1.0, total_trades=5, min_trades=10) is False


def test_meets_deactivation_criteria_true_negative_score_enough_trades():
    assert meets_deactivation_criteria(score=-1.0, total_trades=15, min_trades=10) is True


def test_meets_deactivation_criteria_false_positive_score():
    assert meets_deactivation_criteria(score=1.0, total_trades=15, min_trades=10) is False


def test_meets_deactivation_criteria_false_when_score_none():
    assert meets_deactivation_criteria(score=None, total_trades=15) is False


def test_compute_allocation_fractions_proportional_to_positive_scores():
    result = compute_allocation_fractions({"a": 1.0, "b": 3.0})
    assert result["a"] == 0.25
    assert result["b"] == 0.75


def test_compute_allocation_fractions_ignores_negative_scores():
    result = compute_allocation_fractions({"a": -1.0, "b": 2.0})
    assert result["a"] == 0.0
    assert result["b"] == 1.0


def test_compute_allocation_fractions_all_zero_when_no_positive_score():
    result = compute_allocation_fractions({"a": -1.0, "b": -2.0})
    assert result == {"a": 0.0, "b": 0.0}
