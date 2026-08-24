"""Tests de meta_engine.calibration_lookup (ADR-0009, ADR-0010)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from meta_engine.calibration_lookup import (
    apply_calibration_if_available,
    apply_calibration_if_valid,
    fetch_active_calibration,
)
from shared.calibration_provider import CalibrationRun


def _make_pool(row: dict | None):
    conn = AsyncMock()
    conn.fetchrow.return_value = row

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


@pytest.mark.asyncio
async def test_fetch_active_calibration_returns_none_when_no_active_run():
    pool = _make_pool(row=None)
    result = await fetch_active_calibration(pool)
    assert result is None


@pytest.mark.asyncio
async def test_fetch_active_calibration_returns_id_and_run():
    row = {
        "id": 42,
        "method": "platt_scaling",
        "computed_at": datetime.now(tz=UTC),
        "sample_size": 100,
        "is_validated": True,
        "training_period_start": None,
        "training_period_end": None,
        "brier_score": 0.1,
        "parameters": json.dumps({"intercept": 0.0, "coefficient": 1.0}),
        "reason": None,
    }
    pool = _make_pool(row=row)

    result = await fetch_active_calibration(pool)

    assert result is not None
    calibration_id, calibration = result
    assert calibration_id == 42
    assert calibration.parameters == {"intercept": 0.0, "coefficient": 1.0}


def test_apply_calibration_if_valid_returns_none_when_no_calibration():
    assert apply_calibration_if_valid(None, 0.7) is None


def test_apply_calibration_if_valid_returns_none_when_not_validated():
    calibration = CalibrationRun(
        method="platt_scaling", computed_at=datetime.now(tz=UTC), sample_size=5, is_validated=False
    )
    assert apply_calibration_if_valid(calibration, 0.7) is None


def test_apply_calibration_if_valid_computes_probability_when_validated():
    calibration = CalibrationRun(
        method="platt_scaling",
        computed_at=datetime.now(tz=UTC),
        sample_size=100,
        is_validated=True,
        parameters={"intercept": 0.0, "coefficient": 1.0},
    )
    result = apply_calibration_if_valid(calibration, 0.0)
    assert result == pytest.approx(0.5, abs=1e-9)


# --- ADR-0015 : apply_calibration_if_available (niveau 'preliminary' inclus) ---


def test_apply_calibration_if_available_returns_none_when_no_calibration():
    assert apply_calibration_if_available(None, 0.7) is None


def test_apply_calibration_if_available_returns_none_when_collecting():
    calibration = CalibrationRun(
        method="bayesian_logistic_map", computed_at=datetime.now(tz=UTC), sample_size=2, is_validated=False
    )
    assert apply_calibration_if_available(calibration, 0.7) is None


def test_apply_calibration_if_available_computes_probability_when_preliminary():
    calibration = CalibrationRun(
        method="bayesian_logistic_map",
        computed_at=datetime.now(tz=UTC),
        sample_size=12,
        is_validated=False,
        parameters={"intercept": 0.0, "coefficient": 1.0},
    )
    result = apply_calibration_if_available(calibration, 0.0)
    assert result == pytest.approx(0.5, abs=1e-9)


def test_apply_calibration_if_available_computes_probability_when_validated():
    calibration = CalibrationRun(
        method="platt_scaling",
        computed_at=datetime.now(tz=UTC),
        sample_size=100,
        is_validated=True,
        parameters={"intercept": 0.0, "coefficient": 1.0},
    )
    result = apply_calibration_if_available(calibration, 0.0)
    assert result == pytest.approx(0.5, abs=1e-9)
