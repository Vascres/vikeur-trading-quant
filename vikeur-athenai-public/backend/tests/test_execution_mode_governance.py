"""Tests de execution_mode_governance.main (ADR-0004, ADR-0008, étendu
Étape 6 - "Mur de Fer", 16/08/2026)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from execution_mode_governance.main import (
    CONFIRMATION_PHRASE,
    evaluate_prerequisites,
    request_mode_change,
)


def _make_pool(
    current_mode: str,
    mode_changed_before: bool,
    segment_start: datetime,
    trade_count: int = 100,
    total_pnl: Decimal = Decimal("50"),
    portfolio_taken_at: datetime | None = None,
    portfolio_balance: Decimal = Decimal("1000"),
    attestation_rows: list[dict] | None = None,
    allocation_configured: bool = True,
    has_live_eligible_strategy: bool = True,
):
    attestation_rows = attestation_rows or []

    async def fetchrow_side_effect(query, *args):
        if "SELECT mode FROM execution_mode_state" in query:
            return {"mode": current_mode}
        if "WHERE mode != $1" in query:
            return {"changed_at": segment_start - timedelta(days=1)} if mode_changed_before else None
        if "WHERE mode = $1 AND changed_at > $2" in query:
            return {"changed_at": segment_start}
        if "SELECT MIN(changed_at)" in query:
            return {"changed_at": segment_start}
        if "COUNT(*) AS count" in query:
            return {"count": trade_count, "total_pnl": total_pnl}
        if "FROM portfolio_snapshots" in query:
            return (
                {"taken_at": portfolio_taken_at, "total_value_reference_currency": portfolio_balance}
                if portfolio_taken_at
                else None
            )
        if "FROM capital_allocation_config" in query:
            return {"?column?": 1} if allocation_configured else None
        if "FROM strategy_lifecycle_state" in query:
            return {"?column?": 1} if has_live_eligible_strategy else None
        raise AssertionError(f"Requête fetchrow non attendue : {query}")

    async def fetch_side_effect(query, *args):
        if "DISTINCT ON (key)" in query:
            return attestation_rows
        raise AssertionError(f"Requête fetch non attendue : {query}")

    conn = AsyncMock()
    conn.fetchrow.side_effect = fetchrow_side_effect
    conn.fetch.side_effect = fetch_side_effect
    conn.execute = AsyncMock()

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


def _make_redis(kill_switch_active: bool = False):
    """Étape 6 : le kill switch est lu depuis Redis, pas la base -
    inactif par défaut (conforme) dans ces fixtures."""
    redis_client = AsyncMock()
    redis_client.get.return_value = b"1" if kill_switch_active else None
    return redis_client


def _fully_compliant_pool(current_mode: str = "paper"):
    now = datetime.now(tz=UTC)
    return _make_pool(
        current_mode=current_mode,
        mode_changed_before=True,
        segment_start=now - timedelta(days=40),  # au-delà des 30 jours requis
        trade_count=100,
        total_pnl=Decimal("50"),
        portfolio_taken_at=now - timedelta(seconds=10),
        portfolio_balance=Decimal("350"),
        attestation_rows=[
            {"key": "kill_switch_tested", "attested_at": now - timedelta(days=1)},
            {"key": "backups_verified", "attested_at": now - timedelta(days=1)},
            {"key": "monitoring_active", "attested_at": now - timedelta(days=1)},
        ],
        allocation_configured=True,
        has_live_eligible_strategy=True,
    )


@pytest.mark.asyncio
async def test_evaluate_prerequisites_skips_checks_for_non_real_mode():
    pool, _ = _make_pool(current_mode="paper", mode_changed_before=False, segment_start=datetime.now(tz=UTC))
    evaluation = await evaluate_prerequisites(pool, _make_redis(), "paper")
    assert evaluation.overall_passed is True
    assert evaluation.results == []


@pytest.mark.asyncio
async def test_evaluate_prerequisites_passes_when_fully_compliant():
    pool, _ = _fully_compliant_pool()
    evaluation = await evaluate_prerequisites(pool, _make_redis(), "real")
    assert evaluation.overall_passed is True


@pytest.mark.asyncio
async def test_evaluate_prerequisites_fails_when_duration_insufficient():
    now = datetime.now(tz=UTC)
    pool, _ = _make_pool(
        current_mode="paper",
        mode_changed_before=True,
        segment_start=now - timedelta(days=2),  # bien en dessous du minimum
        trade_count=100,
        total_pnl=Decimal("50"),
        portfolio_taken_at=now,
        attestation_rows=[
            {"key": "kill_switch_tested", "attested_at": now},
            {"key": "backups_verified", "attested_at": now},
            {"key": "monitoring_active", "attested_at": now},
        ],
    )
    evaluation = await evaluate_prerequisites(pool, _make_redis(), "real")
    assert evaluation.overall_passed is False
    assert any(
        r.check_name == "minimum_continuous_mode_duration" and not r.passed for r in evaluation.results
    )


# --- Étape 6 (16/08/2026) : les 4 nouveaux prérequis du "Mur de Fer" ---


@pytest.mark.asyncio
async def test_evaluate_prerequisites_fails_when_kill_switch_active():
    pool, _ = _fully_compliant_pool()
    evaluation = await evaluate_prerequisites(pool, _make_redis(kill_switch_active=True), "real")
    assert evaluation.overall_passed is False
    assert any(r.check_name == "kill_switch_inactive" and not r.passed for r in evaluation.results)


@pytest.mark.asyncio
async def test_evaluate_prerequisites_fails_when_no_capital_allocation_configured():
    pool, _ = _make_pool(
        current_mode="paper",
        mode_changed_before=True,
        segment_start=datetime.now(tz=UTC) - timedelta(days=40),
        portfolio_taken_at=datetime.now(tz=UTC),
        portfolio_balance=Decimal("350"),
        attestation_rows=[
            {"key": "kill_switch_tested", "attested_at": datetime.now(tz=UTC)},
            {"key": "backups_verified", "attested_at": datetime.now(tz=UTC)},
            {"key": "monitoring_active", "attested_at": datetime.now(tz=UTC)},
        ],
        allocation_configured=False,
        has_live_eligible_strategy=True,
    )
    evaluation = await evaluate_prerequisites(pool, _make_redis(), "real")
    assert evaluation.overall_passed is False
    assert any(r.check_name == "capital_allocation_configured" and not r.passed for r in evaluation.results)


@pytest.mark.asyncio
async def test_evaluate_prerequisites_fails_when_exchange_balance_not_positive():
    pool, _ = _make_pool(
        current_mode="paper",
        mode_changed_before=True,
        segment_start=datetime.now(tz=UTC) - timedelta(days=40),
        portfolio_taken_at=datetime.now(tz=UTC),
        portfolio_balance=Decimal("0"),
        attestation_rows=[
            {"key": "kill_switch_tested", "attested_at": datetime.now(tz=UTC)},
            {"key": "backups_verified", "attested_at": datetime.now(tz=UTC)},
            {"key": "monitoring_active", "attested_at": datetime.now(tz=UTC)},
        ],
    )
    evaluation = await evaluate_prerequisites(pool, _make_redis(), "real")
    assert evaluation.overall_passed is False
    assert any(r.check_name == "positive_exchange_balance" and not r.passed for r in evaluation.results)


@pytest.mark.asyncio
async def test_evaluate_prerequisites_fails_without_live_eligible_strategy():
    """Le prérequis "crucial" du mandat : aucune stratégie VALIDATED/PRODUCTION
    -> le mode réel est interdit, même si tout le reste est conforme."""
    pool, _ = _make_pool(
        current_mode="paper",
        mode_changed_before=True,
        segment_start=datetime.now(tz=UTC) - timedelta(days=40),
        portfolio_taken_at=datetime.now(tz=UTC),
        portfolio_balance=Decimal("350"),
        attestation_rows=[
            {"key": "kill_switch_tested", "attested_at": datetime.now(tz=UTC)},
            {"key": "backups_verified", "attested_at": datetime.now(tz=UTC)},
            {"key": "monitoring_active", "attested_at": datetime.now(tz=UTC)},
        ],
        has_live_eligible_strategy=False,
    )
    evaluation = await evaluate_prerequisites(pool, _make_redis(), "real")
    assert evaluation.overall_passed is False
    assert any(r.check_name == "live_eligible_strategy_exists" and not r.passed for r in evaluation.results)


@pytest.mark.asyncio
async def test_request_mode_change_rejects_invalid_mode():
    pool, conn = _make_pool(
        current_mode="paper", mode_changed_before=False, segment_start=datetime.now(tz=UTC)
    )
    published = []

    result = await request_mode_change(
        pool, _make_redis(), "not-a-mode", "operateur", None, lambda t, p: published.append((t, p))
    )

    assert result.accepted is False
    conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_request_mode_change_applies_downgrade_without_confirmation():
    """Une transition qui n'est pas vers 'real' est toujours autorisée
    immédiatement, sans phrase de confirmation ni prérequis (principe :
    réduire le risque n'est jamais bloqué)."""
    pool, conn = _make_pool(
        current_mode="real", mode_changed_before=False, segment_start=datetime.now(tz=UTC)
    )
    published = []

    result = await request_mode_change(
        pool, _make_redis(), "paper", "operateur", None, lambda t, p: published.append((t, p))
    )

    assert result.accepted is True
    assert result.new_mode == "paper"
    conn.execute.assert_called_once()
    assert any(t == "execution_mode_governance.mode_changed" for t, _ in published)


@pytest.mark.asyncio
async def test_request_mode_change_rejects_real_without_confirmation_phrase():
    pool, conn = _make_pool(
        current_mode="paper", mode_changed_before=False, segment_start=datetime.now(tz=UTC)
    )
    published = []

    result = await request_mode_change(
        pool, _make_redis(), "real", "operateur", "mauvaise phrase", lambda t, p: published.append((t, p))
    )

    assert result.accepted is False
    conn.execute.assert_not_called()
    assert any(t == "execution_mode_governance.change_rejected" for t, _ in published)


@pytest.mark.asyncio
async def test_request_mode_change_rejects_real_when_prerequisites_unmet():
    now = datetime.now(tz=UTC)
    pool, conn = _make_pool(
        current_mode="paper",
        mode_changed_before=True,
        segment_start=now - timedelta(days=2),
        portfolio_taken_at=now,
        attestation_rows=[],
    )
    published = []

    result = await request_mode_change(
        pool, _make_redis(), "real", "operateur", CONFIRMATION_PHRASE, lambda t, p: published.append((t, p))
    )

    assert result.accepted is False
    conn.execute.assert_not_called()
    assert result.evaluation is not None
    assert result.evaluation.overall_passed is False


@pytest.mark.asyncio
async def test_request_mode_change_accepts_real_when_all_conditions_met():
    pool, conn = _fully_compliant_pool()
    published = []

    result = await request_mode_change(
        pool, _make_redis(), "real", "operateur", CONFIRMATION_PHRASE, lambda t, p: published.append((t, p))
    )

    assert result.accepted is True
    assert result.new_mode == "real"
    conn.execute.assert_called_once()
    assert any(t == "execution_mode_governance.mode_changed" for t, _ in published)


@pytest.mark.asyncio
async def test_request_mode_change_is_noop_when_already_in_target_mode():
    pool, conn = _make_pool(
        current_mode="paper", mode_changed_before=False, segment_start=datetime.now(tz=UTC)
    )
    published = []

    result = await request_mode_change(
        pool, _make_redis(), "paper", "operateur", None, lambda t, p: published.append((t, p))
    )

    assert result.accepted is True
    assert result.reason == "Déjà dans ce mode."
    conn.execute.assert_not_called()
