"""Fonction commune d'écriture dans `orders` (Phase 6).

Utilisée par les 3 modes d'exécution pour garantir qu'ils écrivent
EXACTEMENT de la même façon, seul `execution_mode` variant (Phase 12, §4).
"""

from decimal import Decimal

import asyncpg


async def insert_order_row(
    db_pool: asyncpg.Pool,
    *,
    risk_check_id: int,
    exchange: str,
    symbol: str,
    side: str,
    execution_mode: str,
    requested_price: Decimal | None,
    requested_quantity: Decimal,
    filled_price: Decimal | None,
    filled_quantity: Decimal | None,
    slippage: Decimal | None,
    status: str,
) -> int:
    async with db_pool.acquire() as conn:
        order_id = await conn.fetchval(
            """
            INSERT INTO orders
                (risk_check_id, exchange, symbol, side, execution_mode,
                 requested_price, requested_quantity, filled_price,
                 filled_quantity, slippage, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING id;
            """,
            risk_check_id,
            exchange,
            symbol,
            side,
            execution_mode,
            requested_price,
            requested_quantity,
            filled_price,
            filled_quantity,
            slippage,
            status,
        )
    return order_id
