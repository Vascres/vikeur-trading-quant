"""Tests de pair_execution.liquidity_simulator (ADR-0021)."""

from __future__ import annotations

from decimal import Decimal

from pair_execution.liquidity_simulator import estimate_fill_probability


def test_zero_or_negative_quantity_returns_zero_probability():
    levels = [(Decimal("100"), Decimal("10"))]
    assert estimate_fill_probability(levels, Decimal("0")) == 0.0
    assert estimate_fill_probability(levels, Decimal("-1")) == 0.0


def test_empty_book_returns_zero_probability():
    assert estimate_fill_probability([], Decimal("1")) == 0.0


def test_very_deep_book_relative_to_size_returns_highest_probability():
    levels = [(Decimal("100"), Decimal("10")), (Decimal("101"), Decimal("10"))]
    # profondeur totale 20, taille demandée 1 -> ratio 20, largement >= 3
    assert estimate_fill_probability(levels, Decimal("1")) == 0.99


def test_thin_book_relative_to_size_returns_lowest_probability():
    levels = [(Decimal("100"), Decimal("1"))]
    # profondeur totale 1, taille demandée 10 -> ratio 0.1, sous le seuil bas
    assert estimate_fill_probability(levels, Decimal("10")) == 0.15


def test_probability_increases_monotonically_with_depth_ratio():
    target = Decimal("10")
    thin = [(Decimal("100"), Decimal("3"))]
    medium = [(Decimal("100"), Decimal("10"))]
    deep = [(Decimal("100"), Decimal("35"))]

    p_thin = estimate_fill_probability(thin, target)
    p_medium = estimate_fill_probability(medium, target)
    p_deep = estimate_fill_probability(deep, target)

    assert p_thin < p_medium < p_deep


def test_probability_always_within_valid_range():
    levels = [(Decimal("100"), Decimal("5"))]
    for qty in [Decimal("0.001"), Decimal("1"), Decimal("5"), Decimal("100"), Decimal("10000")]:
        p = estimate_fill_probability(levels, qty)
        assert 0.0 <= p <= 1.0
