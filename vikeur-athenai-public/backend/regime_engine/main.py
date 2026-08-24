"""Orchestration du calcul de régime de marché (ADR-0011).

Assemble l'historique nécessaire à `regime_engine.detector.detect_regime`
(fonction pure) à partir de `feature_values` déjà historisées - aucune
nouvelle collecte requise - et persiste le résultat dans
`market_regimes`. Invoqué en ligne par `decision_engine` à chaque cycle
d'évaluation, pas comme un service séparé (le régime est un préalable
immédiat à l'évaluation des moteurs, pas une donnée d'arrière-plan).
"""

from __future__ import annotations

import asyncpg

from regime_engine.detector import RegimeResult, detect_regime

# Fenêtre glissante utilisée comme population de référence pour le rang
# percentile (ADR-0011) - configurable, documentée.
HISTORY_WINDOW_SIZE = 500


async def _fetch_feature_history(
    db_pool: asyncpg.Pool, feature_definition_id: int, exchange: str, symbol: str, limit: int
) -> list[float]:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT value FROM feature_values
            WHERE feature_definition_id = $1 AND exchange = $2 AND symbol = $3
            ORDER BY time DESC
            LIMIT $4;
            """,
            feature_definition_id,
            exchange,
            symbol,
            limit,
        )
    return [row["value"] for row in rows]


async def compute_and_persist_regime(
    db_pool: asyncpg.Pool,
    exchange: str,
    symbol: str,
    current_momentum: float,
    current_volatility: float,
    momentum_feature_definition_id: int,
    volatility_feature_definition_id: int,
) -> RegimeResult:
    momentum_history = await _fetch_feature_history(
        db_pool, momentum_feature_definition_id, exchange, symbol, HISTORY_WINDOW_SIZE
    )
    volatility_history = await _fetch_feature_history(
        db_pool, volatility_feature_definition_id, exchange, symbol, HISTORY_WINDOW_SIZE
    )

    result = detect_regime(current_momentum, momentum_history, current_volatility, volatility_history)

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO market_regimes (exchange, symbol, regime_type, confidence, trend, volatility_level)
            VALUES ($1, $2, $3, $4, $5, $6);
            """,
            exchange,
            symbol,
            result.regime_type,
            result.confidence,
            result.trend,
            result.volatility_level,
        )

    return result
