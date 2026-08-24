"""Tests de cost_model.fee_schedule (ADR-0016)."""

from __future__ import annotations

from datetime import UTC, datetime

from cost_model.fee_schedule import (
    DOCUMENTED_FALLBACK,
    MEASURED_API,
    FeeSchedule,
    documented_fallback_schedule,
)


def test_round_trip_taker_fee_is_double_the_one_way_rate():
    schedule = FeeSchedule(
        exchange="htx",
        symbol="BTC/USDT",
        maker_fee_bps=20.0,
        taker_fee_bps=20.0,
        source=MEASURED_API,
        measured_at=datetime.now(tz=UTC),
    )
    assert schedule.round_trip_taker_fee_bps == 40.0


def test_documented_fallback_uses_htx_base_tier_rate():
    schedule = documented_fallback_schedule("htx", "SOL/USDT")
    assert schedule.source == DOCUMENTED_FALLBACK
    assert schedule.taker_fee_bps == 20.0
    assert schedule.round_trip_taker_fee_bps == 40.0
    assert schedule.exchange == "htx"
    assert schedule.symbol == "SOL/USDT"


def test_fallback_is_never_silently_labelled_as_measured():
    schedule = documented_fallback_schedule("htx", "ETH/USDT")
    assert schedule.source != MEASURED_API


# --- Chantier CostModel unique (16/08/2026) : repli par exchange, pas un
# seul tarif HTX appliqué partout ---


def test_documented_fallback_uses_binance_base_tier_rate_not_htx():
    """Piège identifié en écrivant le chantier : avant la table par
    exchange, ce repli aurait silencieusement utilisé le tarif HTX
    (20 bps) pour Binance (10 bps) - deux tarifs de base bien réels mais
    différents."""
    schedule = documented_fallback_schedule("binance", "BTC/USDT")
    assert schedule.exchange == "binance"
    assert schedule.taker_fee_bps == 10.0
    assert schedule.round_trip_taker_fee_bps == 20.0


def test_documented_fallback_unknown_exchange_defaults_to_htx_rate_not_a_crash():
    """Un exchange non encore répertorié ne doit jamais faire planter un
    cycle de mesure - repli sur le tarif HTX en dernier recours, jamais
    une exception."""
    schedule = documented_fallback_schedule("kraken", "BTC/USDT")
    assert schedule.taker_fee_bps == 20.0
