"""Tests de meta_engine.cross_sectional.classify_cross_sectional_ranks (ADR-0017)."""

from __future__ import annotations

import pytest

from meta_engine.cross_sectional import (
    LAGGARD_RANK,
    LEADER_RANK,
    MIDDLE_RANK,
    classify_cross_sectional_ranks,
)


def test_leader_and_laggard_correctly_identified_among_three():
    momentum = {"BTC/USDT": 0.01, "ETH/USDT": 0.03, "SOL/USDT": -0.02}
    ranks = classify_cross_sectional_ranks(momentum)

    assert ranks["ETH/USDT"]["cross_sectional_rank"] == LEADER_RANK
    assert ranks["SOL/USDT"]["cross_sectional_rank"] == LAGGARD_RANK
    assert ranks["BTC/USDT"]["cross_sectional_rank"] == MIDDLE_RANK


def test_spread_is_the_gap_between_leader_and_laggard_for_every_symbol():
    momentum = {"BTC/USDT": 0.01, "ETH/USDT": 0.03, "SOL/USDT": -0.02}
    ranks = classify_cross_sectional_ranks(momentum)

    expected_spread = pytest.approx(0.03 - (-0.02))
    assert ranks["BTC/USDT"]["cross_sectional_spread"] == expected_spread
    assert ranks["ETH/USDT"]["cross_sectional_spread"] == expected_spread
    assert ranks["SOL/USDT"]["cross_sectional_spread"] == expected_spread


def test_returns_middle_rank_for_every_symbol_when_universe_too_small():
    """Univers insuffisant (< 2 symboles) - aucun classement n'a de sens,
    jamais une opinion fabriquée (principe directeur 2)."""
    ranks = classify_cross_sectional_ranks({"BTC/USDT": 0.01})
    assert ranks == {"BTC/USDT": {"cross_sectional_rank": MIDDLE_RANK, "cross_sectional_spread": 0.0}}


def test_empty_universe_returns_empty_dict():
    assert classify_cross_sectional_ranks({}) == {}


def test_two_symbols_only_one_leader_one_laggard_no_middle():
    momentum = {"BTC/USDT": 0.02, "ETH/USDT": -0.01}
    ranks = classify_cross_sectional_ranks(momentum)

    assert ranks["BTC/USDT"]["cross_sectional_rank"] == LEADER_RANK
    assert ranks["ETH/USDT"]["cross_sectional_rank"] == LAGGARD_RANK


def test_all_equal_momentum_yields_zero_spread_and_middle_rank_for_all():
    momentum = {"BTC/USDT": 0.01, "ETH/USDT": 0.01, "SOL/USDT": 0.01}
    ranks = classify_cross_sectional_ranks(momentum)

    assert all(r["cross_sectional_rank"] == MIDDLE_RANK for r in ranks.values())
    assert all(r["cross_sectional_spread"] == 0.0 for r in ranks.values())


def test_negative_momentum_leader_is_the_least_negative():
    """Le "leader" est le moins mauvais, pas nécessairement positif -
    classement relatif, pas absolu (ADR-0017 - toute la différence avec
    le momentum en série temporelle des deux moteurs existants)."""
    momentum = {"BTC/USDT": -0.03, "ETH/USDT": -0.01, "SOL/USDT": -0.05}
    ranks = classify_cross_sectional_ranks(momentum)

    assert ranks["ETH/USDT"]["cross_sectional_rank"] == LEADER_RANK
    assert ranks["SOL/USDT"]["cross_sectional_rank"] == LAGGARD_RANK
