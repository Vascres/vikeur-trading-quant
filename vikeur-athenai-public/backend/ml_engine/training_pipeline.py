"""Pipeline d'entraînement (Phase 16).

Persiste toujours is_active=FALSE (§1/§5) - aucune ligne de ce fichier
ne met ce champ à TRUE. L'activation est un acte humain volontaire
différé à une phase future dédiée.
"""

from __future__ import annotations

import json
from datetime import datetime

import asyncpg

from ml_engine.comparison import evaluate_model
from ml_engine.label_builder import align_features_and_labels, build_labels
from ml_engine.models.gradient_boosting import GradientBoostingModel
from ml_engine.models.random_forest import RandomForestModel

CANDIDATE_MODELS = [GradientBoostingModel, RandomForestModel]
LABEL_HORIZON_PERIODS = 10  # cohérent avec l'horizon minute/heure de la Phase 1
TRAIN_VALIDATION_SPLIT = 0.8  # chronologique, jamais aléatoire (pas de fuite du futur)


async def train_and_compare(
    db_pool: asyncpg.Pool,
    exchange: str,
    symbol: str,
    period_start: datetime,
    period_end: datetime,
    feature_definition_ids: dict[str, int],
) -> list[dict]:
    """Entraîne tous les modèles candidats, les compare, les persiste
    (toujours is_active=FALSE), et retourne un résumé pour information
    humaine - ne déclenche jamais d'activation (Phase 16, §1/§5).
    """
    feature_names = sorted(feature_definition_ids.keys())  # ordre stable des colonnes
    _timestamps, closes, feature_matrix = await _fetch_training_data(
        db_pool, exchange, symbol, period_start, period_end, feature_definition_ids, feature_names
    )

    labels = build_labels(closes, LABEL_HORIZON_PERIODS)
    X, y = align_features_and_labels(feature_matrix, labels)

    forward_returns = [
        (closes[i + LABEL_HORIZON_PERIODS] - closes[i]) / closes[i]
        for i in range(len(closes) - LABEL_HORIZON_PERIODS)
        if labels[i] is not None
    ]

    split_index = int(len(X) * TRAIN_VALIDATION_SPLIT)
    X_train, y_train = X[:split_index], y[:split_index]
    X_val, returns_val = X[split_index:], forward_returns[split_index:]

    summary = []
    for model_class in CANDIDATE_MODELS:
        model = model_class()
        model.fit(X_train, y_train)
        evaluation = evaluate_model(model, X_val, returns_val)

        await _persist_model(db_pool, model, period_start, period_end, evaluation)
        summary.append(
            {
                "model": evaluation.model_name,
                "profit_factor": evaluation.profit_factor,
                "expectancy": evaluation.expectancy,
                "total_simulated_trades": evaluation.total_simulated_trades,
            }
        )

    # Sélection informative uniquement (revue humaine) - voir ml_engine.comparison.select_best_model.
    # Aucune activation automatique n'a lieu ici (Phase 16, §1/§5).
    return summary


async def _fetch_training_data(
    db_pool: asyncpg.Pool,
    exchange: str,
    symbol: str,
    period_start: datetime,
    period_end: datetime,
    feature_definition_ids: dict[str, int],
    feature_names: list[str],
) -> tuple[list[datetime], list[float], list[list[float]]]:
    async with db_pool.acquire() as conn:
        candles = await conn.fetch(
            """
            SELECT bucket, close FROM ohlcv_candles_1m
            WHERE exchange = $1 AND symbol = $2 AND bucket BETWEEN $3 AND $4
            ORDER BY bucket ASC;
            """,
            exchange,
            symbol,
            period_start,
            period_end,
        )

        timestamps = [c["bucket"] for c in candles]
        closes = [float(c["close"]) for c in candles]

        feature_matrix: list[list[float]] = []
        for ts in timestamps:
            row = []
            complete = True
            for name in feature_names:
                value_row = await conn.fetchrow(
                    """
                    SELECT value FROM feature_values
                    WHERE feature_definition_id = $1 AND exchange = $2 AND symbol = $3 AND time <= $4
                    ORDER BY time DESC LIMIT 1;
                    """,
                    feature_definition_ids[name],
                    exchange,
                    symbol,
                    ts,
                )
                if value_row is None:
                    complete = False
                    break
                row.append(value_row["value"])
            feature_matrix.append(row if complete else [float("nan")] * len(feature_names))

    return timestamps, closes, feature_matrix


async def _persist_model(db_pool, model, period_start, period_end, evaluation) -> None:
    async with db_pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT COALESCE(MAX(version), 0) FROM ml_models WHERE name = $1;", model.metadata.name
        )
        await conn.execute(
            """
            INSERT INTO ml_models
                (name, version, algorithm, training_period_start, training_period_end,
                 metrics, serialized_model, is_active)
            VALUES ($1, $2, $3, $4, $5, $6, $7, FALSE);
            """,
            model.metadata.name,
            existing + 1,
            model.metadata.algorithm,
            period_start,
            period_end,
            json.dumps(
                {
                    "profit_factor": evaluation.profit_factor,
                    "expectancy": evaluation.expectancy,
                    "total_simulated_trades": evaluation.total_simulated_trades,
                }
            ),
            model.serialize(),
        )
