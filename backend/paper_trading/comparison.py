"""Comparaison Paper vs Réel (Phase 15, §6 ; demande explicite du brief initial).

Réutilise directement backtesting/metrics.py (Phase 14) - aucune
duplication de la logique de calcul des métriques.
"""

from dataclasses import dataclass
from datetime import datetime

import asyncpg

from backtesting import metrics


@dataclass(frozen=True)
class ModePerformance:
    execution_mode: str
    total_trades: int
    profit_factor: float | None
    expectancy: float | None
    max_drawdown: float | None


async def compare_paper_vs_real(
    db_pool: asyncpg.Pool, exchange: str, symbol: str, period_start: datetime, period_end: datetime
) -> dict[str, ModePerformance]:
    results = {}
    for mode in ("paper", "real"):
        results[mode] = await _compute_mode_performance(
            db_pool, exchange, symbol, mode, period_start, period_end
        )
    return results


async def _compute_mode_performance(
    db_pool: asyncpg.Pool,
    exchange: str,
    symbol: str,
    execution_mode: str,
    period_start: datetime,
    period_end: datetime,
) -> ModePerformance:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT realized_pnl FROM positions
            WHERE exchange = $1 AND symbol = $2 AND execution_mode = $3
              AND status = 'closed' AND closed_at BETWEEN $4 AND $5
            ORDER BY closed_at ASC;
            """,
            exchange,
            symbol,
            execution_mode,
            period_start,
            period_end,
        )

    trade_pnls = [float(r["realized_pnl"]) for r in rows]
    equity_curve = _build_equity_curve(trade_pnls)

    return ModePerformance(
        execution_mode=execution_mode,
        total_trades=len(trade_pnls),
        profit_factor=metrics.profit_factor(trade_pnls),
        expectancy=metrics.expectancy(trade_pnls),
        max_drawdown=metrics.max_drawdown(equity_curve) if equity_curve else None,
    )


def _build_equity_curve(trade_pnls: list[float], starting_value: float = 0.0) -> list[float]:
    """Construit une courbe d'équité cumulative à partir d'une liste de PnL de trades."""
    equity_curve = [starting_value]
    for pnl in trade_pnls:
        equity_curve.append(equity_curve[-1] + pnl)
    return equity_curve
