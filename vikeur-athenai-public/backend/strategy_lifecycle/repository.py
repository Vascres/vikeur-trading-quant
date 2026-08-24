"""Accès base de données du Strategy Lifecycle Manager (Étape 3 du plan
validé le 16/08/2026). Isolé des fonctions pures (`metrics.py`,
`eviction_rules.py`) - même séparation que le reste du projet
(`decision_engine/thresholds.py` vs `decision_engine/main.py`).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import asyncpg

from strategy_lifecycle.metrics import TradeOutcome
from strategy_lifecycle.states import DEFAULT_STATUS_FOR_EXISTING_STRATEGY


async def ensure_lifecycle_row(db_pool: asyncpg.Pool, strategy_id: int) -> None:
    """Initialise une ligne `strategy_lifecycle_state` si absente -
    idempotent (`ON CONFLICT DO NOTHING`). Toute stratégie déjà en
    production au moment où ce chantier est déployé démarre en
    EXPERIMENTAL (cf. docstring de `states.DEFAULT_STATUS_FOR_EXISTING_STRATEGY`),
    jamais REGISTERED (qui impliquerait qu'elle ne tourne pas encore -
    faux pour les moteurs déjà actifs)."""
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO strategy_lifecycle_state (strategy_id, status, reason, sample_size)
            VALUES ($1, $2, 'Initialisation automatique (Étape 3, 16/08/2026).', 0)
            ON CONFLICT (strategy_id) DO NOTHING;
            """,
            strategy_id,
            DEFAULT_STATUS_FOR_EXISTING_STRATEGY,
        )


async def fetch_lifecycle_status(db_pool: asyncpg.Pool, strategy_id: int) -> str | None:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status FROM strategy_lifecycle_state WHERE strategy_id = $1;", strategy_id
        )
    return row["status"] if row is not None else None


async def fetch_all_lifecycle_statuses(db_pool: asyncpg.Pool) -> dict[int, str]:
    """Une requête, pas une par stratégie - lue une fois par cycle par
    `decision_engine/main.py` (même patron que les classements
    cross-sectionnels, ADR-0017)."""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT strategy_id, status FROM strategy_lifecycle_state;")
    return {row["strategy_id"]: row["status"] for row in rows}


async def fetch_transitioned_at(db_pool: asyncpg.Pool, strategy_id: int) -> datetime | None:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT transitioned_at FROM strategy_lifecycle_state WHERE strategy_id = $1;", strategy_id
        )
    return row["transitioned_at"] if row is not None else None


async def fetch_recent_closed_trades(
    db_pool: asyncpg.Pool, strategy_id: int, limit: int, since: datetime | None = None
) -> list[TradeOutcome]:
    """Trades clôturés attribuables à `strategy_id`, triés du plus
    récent au plus ancien, plafonnés à `limit`.

    Couvre les deux chemins d'attribution existants (cf. audit du
    16/08/2026, section "positions n'a pas de strategy_id direct") :
    - direct : `decisions.strategy_id` (pair_execution, tout futur
      moteur non fusionné) ;
    - fusionné : `decisions.meta_decision_id` -> `meta_decisions.
      contributing_opinion_ids` -> `engine_opinions.strategy_id` (les 3
      moteurs directionnels actifs aujourd'hui, dont les décisions
      passent toujours par la fusion, `decisions.strategy_id` y étant
      systématiquement NULL).

    `since`, si fourni, restreint aux trades clôturés strictement après
    cette date - utilisé pour les métriques de quarantaine (résurrection),
    jamais pour l'éviction (qui regarde la fenêtre glissante complète)."""
    since_clause = "AND p.closed_at > $3" if since is not None else ""

    query = f"""
        SELECT realized_pnl, entry_price, quantity, closed_at FROM (
            SELECT p.id, p.realized_pnl, p.entry_price, p.quantity, p.closed_at
            FROM positions p
            JOIN decisions d ON d.id = p.decision_id
            WHERE d.strategy_id = $1 AND p.status = 'closed' AND p.realized_pnl IS NOT NULL {since_clause}

            UNION

            SELECT p.id, p.realized_pnl, p.entry_price, p.quantity, p.closed_at
            FROM positions p
            JOIN decisions d ON d.id = p.decision_id
            JOIN meta_decisions md ON md.id = d.meta_decision_id
            JOIN engine_opinions eo ON eo.id = ANY(md.contributing_opinion_ids)
            WHERE eo.strategy_id = $1 AND p.status = 'closed' AND p.realized_pnl IS NOT NULL {since_clause}
        ) combined
        ORDER BY closed_at DESC
        LIMIT $2;
    """
    # $2 doit rester `limit` dans les deux branches - si `since` est fourni,
    # il occupe $3 et la clause l'utilise dans les deux UNION, `limit` reste $2.
    query_params = [strategy_id, limit] if since is None else [strategy_id, limit, since]

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(query, *query_params)

    return [
        TradeOutcome(
            realized_pnl=Decimal(str(row["realized_pnl"])),
            entry_notional=Decimal(str(row["entry_price"])) * Decimal(str(row["quantity"])),
        )
        for row in rows
    ]


async def fetch_reference_capital(db_pool: asyncpg.Pool, exchange: str) -> Decimal | None:
    """Repli documenté (cf. docstring de `eviction_rules.determine_eviction_transition`) :
    aucune allocation par stratégie n'existe encore (Étape 5 du plan,
    "Dual Portfolio") - le capital total du dernier instantané de
    portefeuille sert de référence pour le calcul de drawdown, en
    attendant. Retourne `None` si aucun instantané n'existe, jamais une
    valeur inventée (même principe que `risk_engine.main.PortfolioUnavailableError`)."""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT total_value_reference_currency FROM portfolio_snapshots
            WHERE exchange = $1 AND market_type IS NULL
            ORDER BY taken_at DESC LIMIT 1;
            """,
            exchange,
        )
    return Decimal(str(row["total_value_reference_currency"])) if row is not None else None


async def apply_transition(
    db_pool: asyncpg.Pool,
    strategy_id: int,
    previous_status: str,
    new_status: str,
    reason: str,
    ev_net_bps: float | None,
    cumulative_pnl: Decimal,
    profit_factor: float | None,
    sample_size: int,
) -> None:
    """Écrit la nouvelle ligne `strategy_lifecycle_state` (UPSERT) ET une
    ligne `strategy_lifecycle_history` append-only (Règle Absolue du
    mandat : "Ne jamais supprimer les données historiques d'une
    stratégie suspendue") - les deux dans la même transaction, jamais
    l'une sans l'autre."""
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO strategy_lifecycle_state
                    (strategy_id, status, reason, ev_net_bps, cumulative_pnl_reference_currency,
                     profit_factor, sample_size, transitioned_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, now())
                ON CONFLICT (strategy_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    reason = EXCLUDED.reason,
                    ev_net_bps = EXCLUDED.ev_net_bps,
                    cumulative_pnl_reference_currency = EXCLUDED.cumulative_pnl_reference_currency,
                    profit_factor = EXCLUDED.profit_factor,
                    sample_size = EXCLUDED.sample_size,
                    transitioned_at = EXCLUDED.transitioned_at;
                """,
                strategy_id,
                new_status,
                reason,
                ev_net_bps,
                cumulative_pnl,
                profit_factor,
                sample_size,
            )
            await conn.execute(
                """
                INSERT INTO strategy_lifecycle_history
                    (strategy_id, previous_status, new_status, reason, ev_net_bps,
                     cumulative_pnl_reference_currency, profit_factor, sample_size)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8);
                """,
                strategy_id,
                previous_status,
                new_status,
                reason,
                ev_net_bps,
                cumulative_pnl,
                profit_factor,
                sample_size,
            )


async def fetch_active_strategy_ids(db_pool: asyncpg.Pool) -> list[int]:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT id FROM strategies WHERE is_active = TRUE;")
    return [row["id"] for row in rows]
