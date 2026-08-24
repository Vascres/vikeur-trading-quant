"""Tests de calibration.bayesian_provider.BayesianCalibrationProvider
(ADR-0015)."""

from __future__ import annotations

import random

import pytest

from calibration.bayesian_provider import BayesianCalibrationProvider


def _make_separable_dataset(n: int = 60, seed: int = 42) -> tuple[list[float], list[bool]]:
    rng = random.Random(seed)
    scores = [rng.uniform(0.3, 0.9) for _ in range(n)]
    outcomes = [rng.random() < score for score in scores]
    return scores, outcomes


@pytest.mark.asyncio
async def test_below_preliminary_threshold_returns_collecting_with_prior_parameters():
    provider = BayesianCalibrationProvider(minimum_sample_size_preliminary=5)
    scores, outcomes = _make_separable_dataset(n=3)

    calibration = await provider.calibrate(scores, outcomes)

    assert calibration.is_validated is False
    assert calibration.sample_size == 3
    assert calibration.parameters == {"intercept": 0.0, "coefficient": 0.0}
    assert "preliminaire" in calibration.reason.lower() or "préliminaire" in calibration.reason.lower()
    # Prior non informatif -> probabilité de succès = 50% quel que soit le score.
    assert provider.apply(calibration, 0.9) == pytest.approx(0.5, abs=1e-9)


@pytest.mark.asyncio
async def test_preliminary_level_produces_usable_but_unvalidated_probability():
    provider = BayesianCalibrationProvider(
        minimum_sample_size_preliminary=5, minimum_sample_size_validated=30
    )
    scores, outcomes = _make_separable_dataset(n=12, seed=1)

    calibration = await provider.calibrate(scores, outcomes)

    assert calibration.sample_size == 12
    assert calibration.is_validated is False
    assert "preliminary" in calibration.reason.lower()
    # Une probabilité doit malgré tout être calculable (contrairement à
    # LogisticCalibrationProvider, ADR-0009, qui refuse en dessous de 30).
    probability = provider.apply(calibration, 0.8)
    assert 0.0 <= probability <= 1.0


@pytest.mark.asyncio
async def test_validated_level_reached_with_sufficient_correlated_data():
    provider = BayesianCalibrationProvider()
    scores, outcomes = _make_separable_dataset(n=200, seed=7)

    calibration = await provider.calibrate(scores, outcomes)

    assert calibration.sample_size == 200
    assert calibration.brier_score is not None
    assert calibration.is_validated is True
    assert calibration.reason is None


@pytest.mark.asyncio
async def test_regularization_shrinks_coefficient_towards_zero_at_low_sample_size():
    """Vérifie l'intuition bayésienne centrale (ADR-0015) : à échantillon
    égal (mêmes données dupliquées), une régularisation plus forte (n bas)
    doit produire un coefficient de plus faible amplitude qu'une
    régularisation plus faible (n haut) - preuve que le "retrait vers le
    prior" fonctionne bien dans le sens attendu."""
    scores, outcomes = _make_separable_dataset(n=25, seed=3)

    low_n_provider = BayesianCalibrationProvider(minimum_sample_size_preliminary=5)
    high_n_provider = BayesianCalibrationProvider(minimum_sample_size_preliminary=5)

    # Même distribution de signal, mais l'un est évalué comme s'il avait
    # peu de données (régularisation forte), l'autre comme s'il en avait
    # beaucoup (régularisation faible) - en dupliquant le dataset.
    low_n_calibration = await low_n_provider.calibrate(scores, outcomes)
    high_n_calibration = await high_n_provider.calibrate(scores * 10, outcomes * 10)

    assert abs(low_n_calibration.parameters["coefficient"]) <= abs(
        high_n_calibration.parameters["coefficient"]
    )


@pytest.mark.asyncio
async def test_degenerate_training_set_falls_back_to_prior_instead_of_refusing():
    provider = BayesianCalibrationProvider(minimum_sample_size_preliminary=5)
    scores = [0.5] * 20
    outcomes = [True] * 20  # un seul type d'issue dans l'entraînement

    calibration = await provider.calibrate(scores, outcomes)

    # Contrairement à LogisticCalibrationProvider (ADR-0009), l'échec de
    # l'ajustement retombe sur le prior plutôt que d'être un refus pur.
    assert calibration.parameters == {"intercept": 0.0, "coefficient": 0.0}
    assert calibration.sample_size == 20


def test_apply_matches_known_logistic_formula():
    from datetime import UTC, datetime

    from shared.calibration_provider import CalibrationRun

    provider = BayesianCalibrationProvider()
    calibration = CalibrationRun(
        method="bayesian_logistic_map",
        computed_at=datetime.now(tz=UTC),
        sample_size=12,
        is_validated=False,
        parameters={"intercept": 0.0, "coefficient": 1.0},
    )

    assert provider.apply(calibration, 0.0) == pytest.approx(0.5, abs=1e-9)
