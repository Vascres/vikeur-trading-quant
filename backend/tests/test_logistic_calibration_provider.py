"""Tests de calibration.logistic_provider.LogisticCalibrationProvider
(ADR-0009)."""

from __future__ import annotations

import random

import pytest

from calibration.logistic_provider import LogisticCalibrationProvider


def _make_separable_dataset(n: int = 60, seed: int = 42) -> tuple[list[float], list[bool]]:
    """Scores et issues corrélés de façon simple mais bruitée - suffisant
    pour qu'une régression logistique trouve un signal net, sans être
    un cas dégénéré (toujours vrai / toujours faux)."""
    rng = random.Random(seed)
    scores = [rng.uniform(0.3, 0.9) for _ in range(n)]
    outcomes = [rng.random() < score for score in scores]  # corrélation directe score -> issue
    return scores, outcomes


@pytest.mark.asyncio
async def test_calibrate_fails_validation_when_sample_too_small():
    provider = LogisticCalibrationProvider(minimum_sample_size=30)
    scores, outcomes = _make_separable_dataset(n=10)

    calibration = await provider.calibrate(scores, outcomes)

    assert calibration.is_validated is False
    assert calibration.sample_size == 10
    assert "insuffisant" in calibration.reason.lower()


@pytest.mark.asyncio
async def test_calibrate_fails_validation_when_training_set_has_single_outcome():
    provider = LogisticCalibrationProvider(minimum_sample_size=10)
    scores = [0.5] * 40
    outcomes = [True] * 40  # jamais de perte dans l'échantillon

    calibration = await provider.calibrate(scores, outcomes)

    assert calibration.is_validated is False
    assert calibration.sample_size == 40


@pytest.mark.asyncio
async def test_calibrate_succeeds_with_sufficient_correlated_data():
    provider = LogisticCalibrationProvider(minimum_sample_size=30)
    scores, outcomes = _make_separable_dataset(n=200, seed=7)

    calibration = await provider.calibrate(scores, outcomes)

    assert calibration.sample_size == 200
    assert calibration.brier_score is not None
    assert "intercept" in calibration.parameters
    assert "coefficient" in calibration.parameters
    # Avec un signal aussi net (issue tirée directement du score), le
    # Brier score de validation doit être nettement meilleur que 0.25.
    assert calibration.is_validated is True


@pytest.mark.asyncio
async def test_apply_is_monotonic_in_raw_score():
    provider = LogisticCalibrationProvider(minimum_sample_size=30)
    scores, outcomes = _make_separable_dataset(n=200, seed=7)
    calibration = await provider.calibrate(scores, outcomes)

    low = provider.apply(calibration, 0.1)
    high = provider.apply(calibration, 0.9)

    assert 0.0 <= low <= 1.0
    assert 0.0 <= high <= 1.0
    assert high > low


def test_apply_matches_known_logistic_formula():
    from shared.calibration_provider import CalibrationRun
    from datetime import UTC, datetime

    provider = LogisticCalibrationProvider()
    calibration = CalibrationRun(
        method="platt_scaling",
        computed_at=datetime.now(tz=UTC),
        sample_size=100,
        is_validated=True,
        parameters={"intercept": 0.0, "coefficient": 1.0},
    )

    # sigmoid(0) = 0.5 exactement quand intercept=0, coefficient=1, score=0
    assert provider.apply(calibration, 0.0) == pytest.approx(0.5, abs=1e-9)
