"""Tests de decision_engine.main._derive_verdict (ADR-0014, ADR-0015).

Fonction pure isolant toute la logique de gouvernance mode d'exécution
x niveau de maturité du Confidence Lifecycle - le cœur de la résolution
du deadlock calibration/trades.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from decision_engine.main import _derive_verdict
from shared.calibration_provider import CalibrationRun
from shared.confidence_lifecycle import COLLECTING, PRELIMINARY, VALIDATED

# intercept=2.0, coefficient=1.0 -> sigmoid(2.0 + 1.0*0.5) ~ 0.924, passe
# largement le seuil de probabilité calibrée (0.55).
_STRONG_PARAMETERS = {"intercept": 2.0, "coefficient": 1.0}


def _calibration(sample_size: int, is_validated: bool, parameters: dict | None = None) -> CalibrationRun:
    return CalibrationRun(
        method="bayesian_logistic_map",
        computed_at=datetime.now(tz=UTC),
        sample_size=sample_size,
        is_validated=is_validated,
        parameters=parameters or _STRONG_PARAMETERS,
    )


# --- Mode réel : jamais de bootstrap ni de 'preliminary' ---


def test_real_mode_no_calibration_is_insufficient():
    verdict, probability, maturity, reason = _derive_verdict("real", 0.8, None, 0.005, 2.0)
    assert verdict == "insufficient_calibration"
    assert probability is None
    assert maturity == COLLECTING
    assert "réel" in reason.lower()


def test_real_mode_preliminary_calibration_is_insufficient():
    calibration = _calibration(sample_size=12, is_validated=False)
    verdict, probability, maturity, _reason = _derive_verdict("real", 0.8, calibration, 0.005, 2.0)
    assert verdict == "insufficient_calibration"
    assert probability is None
    assert maturity == PRELIMINARY


def test_real_mode_validated_calibration_can_produce_signal():
    calibration = _calibration(sample_size=100, is_validated=True)
    verdict, probability, maturity, _reason = _derive_verdict("real", 0.5, calibration, 0.005, 2.0)
    assert maturity == VALIDATED
    assert probability == pytest.approx(0.924, abs=1e-2)
    assert verdict == "signal"


# --- Mode paper : bootstrap (collecting) et preliminary autorisés ---


def test_paper_mode_collecting_uses_bootstrap_and_can_signal():
    verdict, probability, maturity, reason = _derive_verdict("paper", 0.80, None, 0.005, 2.0)
    assert maturity == COLLECTING
    assert probability is None  # ADR-0014 : score brut, jamais une probabilité inventée
    assert verdict == "signal"
    assert "score brut" in reason.lower() or "bootstrap" in reason.lower() or "démarrage" in reason.lower()


def test_paper_mode_collecting_respects_bootstrap_threshold():
    # 0.60 < seuil bootstrap (0.75) -> pas de signal, même en paper.
    verdict, _probability, _maturity, _reason = _derive_verdict("paper", 0.60, None, 0.005, 2.0)
    assert verdict == "no_signal"


def test_paper_mode_preliminary_calibration_can_signal():
    calibration = _calibration(sample_size=12, is_validated=False)
    verdict, probability, maturity, reason = _derive_verdict("paper", 0.5, calibration, 0.005, 2.0)
    assert maturity == PRELIMINARY
    assert probability == pytest.approx(0.924, abs=1e-2)
    assert verdict == "signal"
    assert "preliminary" in reason.lower()


def test_backtest_mode_treated_like_paper_for_bootstrap():
    verdict, _probability, maturity, _reason = _derive_verdict("backtest", 0.80, None, 0.005, 2.0)
    assert maturity == COLLECTING
    assert verdict == "signal"


# --- Coûts non estimables : prudence systématique, quel que soit le mode ---


def test_missing_expected_value_always_yields_no_signal():
    calibration = _calibration(sample_size=100, is_validated=True)
    verdict, probability, _maturity, reason = _derive_verdict("real", 0.8, calibration, None, 2.0)
    assert verdict == "no_signal"
    assert probability is None
    assert "estimable" in reason.lower()


def test_missing_risk_reward_ratio_always_yields_no_signal():
    verdict, _probability, _maturity, _reason = _derive_verdict("paper", 0.8, None, 0.005, None)
    assert verdict == "no_signal"


# --- ADR-0016 : _fetch_round_trip_fee_bps ---


@pytest.mark.asyncio
async def test_fetch_round_trip_fee_bps_uses_measured_schedule_when_present():
    from unittest.mock import AsyncMock, MagicMock

    from decision_engine.main import _fetch_round_trip_fee_bps

    conn = AsyncMock()
    conn.fetchrow.return_value = {"taker_fee_bps": 15.0, "source": "measured_api"}
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    round_trip_bps, source = await _fetch_round_trip_fee_bps(pool, "htx", "BTC/USDT")

    assert round_trip_bps == pytest.approx(30.0)
    assert source == "measured_api"


@pytest.mark.asyncio
async def test_fetch_round_trip_fee_bps_falls_back_when_no_schedule_persisted_yet():
    from unittest.mock import AsyncMock, MagicMock

    from decision_engine.main import _fetch_round_trip_fee_bps

    conn = AsyncMock()
    conn.fetchrow.return_value = None
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    round_trip_bps, source = await _fetch_round_trip_fee_bps(pool, "htx", "BTC/USDT")

    assert round_trip_bps == pytest.approx(40.0)  # repli documenté (20 bps/jambe, tarif HTX de base)
    assert source == "documented_fallback"


# --- Chantier de routage par market_type (16/08/2026) ---


@pytest.mark.asyncio
async def test_fetch_round_trip_fee_bps_uses_binance_futures_fallback_never_the_spot_schedule():
    """Le point central du correctif : `fee_schedule` reste scopé au spot
    (Étape 2) - une décision futures ne doit JAMAIS lire cette table,
    jamais confondre un tarif spot (10-20 bps) avec un tarif futures
    (~5 bps) - même si `fee_schedule` contenait par erreur une ligne
    pour ce couple (exchange, symbole), elle ne doit jamais être
    consultée pour `market_type='futures_perpetual'`."""
    from unittest.mock import AsyncMock, MagicMock

    from decision_engine.main import _fetch_round_trip_fee_bps

    conn = AsyncMock()
    conn.fetchrow.return_value = {"taker_fee_bps": 20.0, "source": "measured_api"}  # ne doit jamais être lu
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    round_trip_bps, source = await _fetch_round_trip_fee_bps(
        pool, "binance", "BTC/USDT", market_type="futures_perpetual"
    )

    assert round_trip_bps == pytest.approx(10.0)  # 5 bps/jambe (repli documenté Binance futures) x 2
    assert source == "documented_fallback"
    conn.fetchrow.assert_not_awaited()  # fee_schedule jamais interrogée pour du futures


# --- ADR-0017 : _fetch_cross_sectional_ranks ---


@pytest.mark.asyncio
async def test_fetch_cross_sectional_ranks_returns_empty_when_momentum_not_registered():
    from decision_engine.main import _fetch_cross_sectional_ranks

    ranks = await _fetch_cross_sectional_ranks(None, "htx", ["BTC/USDT"], momentum_feature_definition_id=None)

    assert ranks == {}


@pytest.mark.asyncio
async def test_fetch_cross_sectional_ranks_classifies_from_latest_momentum_per_symbol():
    from unittest.mock import AsyncMock, MagicMock

    from decision_engine.main import _fetch_cross_sectional_ranks

    conn = AsyncMock()
    conn.fetchrow.side_effect = [
        {"value": 0.02},  # BTC/USDT
        {"value": 0.05},  # ETH/USDT
        {"value": -0.01},  # SOL/USDT
    ]
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    ranks = await _fetch_cross_sectional_ranks(
        pool, "htx", ["BTC/USDT", "ETH/USDT", "SOL/USDT"], momentum_feature_definition_id=1
    )

    assert ranks["ETH/USDT"]["cross_sectional_rank"] == 1.0
    assert ranks["SOL/USDT"]["cross_sectional_rank"] == -1.0
    assert ranks["BTC/USDT"]["cross_sectional_rank"] == 0.0
