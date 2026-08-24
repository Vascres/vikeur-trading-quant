"""Tests de regime_engine.main.compute_and_persist_regime (ADR-0011)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from regime_engine.main import compute_and_persist_regime


def _make_pool(momentum_history: list[float], volatility_history: list[float]):
    conn = AsyncMock()

    async def fetch_side_effect(query, feature_definition_id, exchange, symbol, limit):
        # Distingue les deux appels par l'id de feature_definition passé
        # (1 = momentum, 2 = volatility dans ces tests).
        history = momentum_history if feature_definition_id == 1 else volatility_history
        return [{"value": v} for v in history]

    conn.fetch.side_effect = fetch_side_effect
    conn.execute = AsyncMock()

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


@pytest.mark.asyncio
async def test_persists_detected_regime():
    pool, conn = _make_pool(momentum_history=[0.001] * 60, volatility_history=[0.01] * 60)

    result = await compute_and_persist_regime(
        pool,
        exchange="htx",
        symbol="BTC/USDT",
        current_momentum=0.05,
        current_volatility=0.05,
        momentum_feature_definition_id=1,
        volatility_feature_definition_id=2,
    )

    assert result.regime_type == "bullish_high_volatility"
    conn.execute.assert_called_once()
    insert_call = conn.execute.call_args
    assert "INSERT INTO market_regimes" in insert_call.args[0]
    assert insert_call.args[3] == "bullish_high_volatility"  # regime_type positionnel


@pytest.mark.asyncio
async def test_returns_unknown_when_history_insufficient():
    pool, conn = _make_pool(momentum_history=[0.01] * 5, volatility_history=[0.01] * 5)

    result = await compute_and_persist_regime(
        pool,
        exchange="htx",
        symbol="BTC/USDT",
        current_momentum=0.02,
        current_volatility=0.02,
        momentum_feature_definition_id=1,
        volatility_feature_definition_id=2,
    )

    assert result.regime_type == "unknown"
    # Toujours persisté, même "unknown" - traçabilité complète (principe 1).
    conn.execute.assert_called_once()
