"""Tests de shared.confidence_lifecycle (ADR-0015)."""

from __future__ import annotations

from datetime import UTC, datetime

from shared.calibration_provider import CalibrationRun
from shared.confidence_lifecycle import (
    COLLECTING,
    PRELIMINARY,
    VALIDATED,
    classify_calibration_maturity,
)


def _run(sample_size: int, is_validated: bool) -> CalibrationRun:
    return CalibrationRun(
        method="bayesian_logistic_map",
        computed_at=datetime.now(tz=UTC),
        sample_size=sample_size,
        is_validated=is_validated,
    )


def test_no_calibration_is_collecting():
    assert classify_calibration_maturity(None) == COLLECTING


def test_below_preliminary_sample_size_is_collecting():
    assert classify_calibration_maturity(_run(sample_size=2, is_validated=False)) == COLLECTING


def test_between_preliminary_and_validated_sample_size_is_preliminary():
    assert classify_calibration_maturity(_run(sample_size=12, is_validated=False)) == PRELIMINARY


def test_validated_flag_takes_precedence():
    assert classify_calibration_maturity(_run(sample_size=100, is_validated=True)) == VALIDATED


def test_preliminary_boundary_is_inclusive():
    assert classify_calibration_maturity(_run(sample_size=5, is_validated=False)) == PRELIMINARY
