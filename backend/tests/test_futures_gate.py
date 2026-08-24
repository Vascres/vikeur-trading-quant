"""Tests de execution_mode_governance.futures_gate (ADR-0018)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from execution_mode_governance.futures_gate import is_futures_real_trading_enabled


def _pool(row):
    conn = AsyncMock()
    conn.fetchrow.return_value = row
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


@pytest.mark.asyncio
async def test_returns_false_when_no_attestation_exists():
    pool = _pool(None)
    assert await is_futures_real_trading_enabled(pool) is False


@pytest.mark.asyncio
async def test_returns_true_when_attestation_exists():
    pool = _pool({"1": 1})
    assert await is_futures_real_trading_enabled(pool) is True
