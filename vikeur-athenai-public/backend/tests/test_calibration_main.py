"""Tests de calibration.main.run_calibration_cycle (ADR-0009).

Utilise un CalibrationProvider factice pour isoler la logique
d'orchestration (persistance, activation/désactivation) de la méthode
statistique elle-même (déjà testée dans test_logistic_calibration_provider.py).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from calibration.main import run_calibration_cycle
from shared.calibration_provider import CalibrationProvider, CalibrationRun


class _FakeProvider(CalibrationProvider):
    method_name = "fake"

    def __init__(self, result: CalibrationRun) -> None:
        self._result = result

    async def calibrate(self, historical_scores, historical_outcomes) -> CalibrationRun:
        return self._result

    def apply(self, calibration, raw_score):
        raise NotImplementedError


def _make_pool(rows: list[dict]):
    conn = AsyncMock()
    conn.fetch.return_value = rows
    conn.execute = AsyncMock()

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


@pytest.mark.asyncio
async def test_validated_result_deactivates_previous_and_inserts_new():
    pool, conn = _make_pool(
        rows=[
            {"raw_score": 0.7, "realized_pnl": Decimal("10"), "closed_at": datetime(2026, 1, 1, tzinfo=UTC)},
            {"raw_score": 0.6, "realized_pnl": Decimal("-5"), "closed_at": datetime(2026, 1, 2, tzinfo=UTC)},
        ]
    )
    provider = _FakeProvider(
        CalibrationRun(
            method="fake", computed_at=datetime.now(tz=UTC), sample_size=2, is_validated=True, brier_score=0.1
        )
    )
    published = []

    result = await run_calibration_cycle(pool, lambda t, p: published.append((t, p)), provider=provider)

    assert result.is_validated is True
    # Une requête UPDATE (désactivation) + une requête INSERT
    assert conn.execute.call_count == 2
    deactivate_call = conn.execute.call_args_list[0]
    assert "is_active = FALSE" in deactivate_call.args[0]
    assert any(t == "calibration.run_completed" for t, _ in published)


@pytest.mark.asyncio
async def test_unvalidated_result_never_deactivates_previous():
    pool, conn = _make_pool(rows=[])
    provider = _FakeProvider(
        CalibrationRun(
            method="fake",
            computed_at=datetime.now(tz=UTC),
            sample_size=0,
            is_validated=False,
            reason="Échantillon insuffisant.",
        )
    )
    published = []

    result = await run_calibration_cycle(pool, lambda t, p: published.append((t, p)), provider=provider)

    assert result.is_validated is False
    # Seule la requête INSERT - jamais de désactivation de la précédente
    assert conn.execute.call_count == 1
    insert_call = conn.execute.call_args_list[0]
    assert "INSERT INTO calibration_runs" in insert_call.args[0]


@pytest.mark.asyncio
async def test_training_period_derived_from_closed_positions():
    pool, _conn = _make_pool(
        rows=[
            {"raw_score": 0.7, "realized_pnl": Decimal("10"), "closed_at": datetime(2026, 1, 1, tzinfo=UTC)},
            {"raw_score": 0.6, "realized_pnl": Decimal("-5"), "closed_at": datetime(2026, 2, 1, tzinfo=UTC)},
        ]
    )
    provider = _FakeProvider(
        CalibrationRun(method="fake", computed_at=datetime.now(tz=UTC), sample_size=2, is_validated=False)
    )

    result = await run_calibration_cycle(pool, lambda t, p: None, provider=provider)

    assert result.training_period_start == datetime(2026, 1, 1, tzinfo=UTC)
    assert result.training_period_end == datetime(2026, 2, 1, tzinfo=UTC)
