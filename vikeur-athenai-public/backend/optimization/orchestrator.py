"""Orchestration de l'optimisation automatique (Phase 17).

Désactivation automatique (direction sûre, comme le kill switch - Phase 13).
Allocation : recommandation persistée uniquement, jamais appliquée
automatiquement (Phase 17, §3).
"""

from __future__ import annotations

import asyncpg

from optimization.capital_allocator import compute_allocation_fractions
from optimization.performance_evaluator import compute_strategy_score, meets_deactivation_criteria

ROLLING_WINDOW_TRADES = 30


async def run_optimization_cycle(db_pool: asyncpg.Pool, publish_journal_event=None) -> dict:
    async with db_pool.acquire() as conn:
        active_strategies = await conn.fetch("SELECT id, name FROM strategies WHERE is_active = TRUE;")

    scores: dict[str, float] = {}
    trade_counts: dict[str, int] = {}
    strategy_ids: dict[str, int] = {}

    for strategy in active_strategies:
        strategy_ids[strategy["name"]] = strategy["id"]

        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT p.realized_pnl FROM positions p
                JOIN decisions d ON d.id = p.decision_id
                WHERE d.strategy_id = $1 AND p.status = 'closed' AND p.execution_mode = 'paper'
                ORDER BY p.closed_at DESC
                LIMIT $2;
                """,
                strategy["id"],
                ROLLING_WINDOW_TRADES,
            )

        trade_pnls = [float(r["realized_pnl"]) for r in rows]
        score = compute_strategy_score(trade_pnls)
        trade_counts[strategy["name"]] = len(trade_pnls)

        if meets_deactivation_criteria(score, len(trade_pnls)):
            async with db_pool.acquire() as conn:
                await conn.execute("UPDATE strategies SET is_active = FALSE WHERE id = $1;", strategy["id"])
            if publish_journal_event:
                publish_journal_event(
                    "optimization.strategy_deactivated",
                    {"strategy": strategy["name"], "score": score, "trades": len(trade_pnls)},
                )
            continue  # exclue du calcul d'allocation ci-dessous

        if score is not None:
            scores[strategy["name"]] = score

    allocations = compute_allocation_fractions(scores) if scores else {}

    async with db_pool.acquire() as conn:
        for name, fraction in allocations.items():
            await conn.execute(
                """
                INSERT INTO strategy_allocations (strategy_id, recommended_fraction, based_on_trade_count, applied)
                VALUES ($1, $2, $3, FALSE);
                """,
                strategy_ids[name],
                fraction,
                trade_counts[name],
            )

    if publish_journal_event:
        publish_journal_event("optimization.cycle_completed", {"scores": scores, "allocations": allocations})

    return {"scores": scores, "allocations": allocations}
