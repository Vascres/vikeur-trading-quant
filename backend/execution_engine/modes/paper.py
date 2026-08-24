"""Mode Paper (Phase 12, §4).

Utilise le prix de marché RÉEL courant (dernière candle), mais ne
contacte jamais l'exchange pour passer un ordre - simule le remplissage.
"""

from decimal import Decimal

import asyncpg

from execution_engine.common import insert_order_row
from execution_engine.positions import apply_fill
from shared.execution_mode import ExecutionMode, OrderResult

# Même modèle de coûts que le backtest par cohérence (Phase 12, §4) -
# à calibrer conjointement en Phase 14/15.
ASSUMED_SLIPPAGE_BPS = Decimal("5")
ASSUMED_FEE_BPS = Decimal("10")


class PaperExecutionMode(ExecutionMode):
    mode_name = "paper"

    def __init__(self, db_pool: asyncpg.Pool) -> None:
        self._db_pool = db_pool

    async def _get_current_price(self, exchange: str, symbol: str) -> Decimal:
        async with self._db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT close FROM ohlcv_candles_1m
                WHERE exchange = $1 AND symbol = $2
                ORDER BY bucket DESC
                LIMIT 1;
                """,
                exchange,
                symbol,
            )
        if row is None:
            raise RuntimeError(
                f"Aucun prix de marché disponible pour {symbol} sur {exchange} - "
                "le paper trading ne peut pas simuler un remplissage sans donnée fraîche."
            )
        return Decimal(str(row["close"]))

    async def execute(
        self,
        risk_check_id: int,
        decision_id: int,
        exchange: str,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal | None = None,
        market_type: str = "spot",
    ) -> OrderResult:
        current_price = price if price is not None else await self._get_current_price(exchange, symbol)

        cost_bps = ASSUMED_SLIPPAGE_BPS + ASSUMED_FEE_BPS
        direction = 1 if side == "buy" else -1
        filled_price = current_price * (1 + direction * cost_bps / Decimal(10_000))
        slippage = abs(filled_price - current_price)

        order_id = await insert_order_row(
            self._db_pool,
            risk_check_id=risk_check_id,
            exchange=exchange,
            symbol=symbol,
            side=side,
            execution_mode=self.mode_name,
            requested_price=current_price,
            requested_quantity=quantity,
            filled_price=filled_price,
            filled_quantity=quantity,
            slippage=slippage,
            status="filled",
        )

        await apply_fill(
            self._db_pool,
            exchange=exchange,
            symbol=symbol,
            execution_mode=self.mode_name,
            side=side,
            filled_price=filled_price,
            filled_quantity=quantity,
            decision_id=decision_id,
            market_type=market_type,
        )

        return OrderResult(
            order_id=str(order_id),
            status="filled",
            filled_price=filled_price,
            filled_quantity=quantity,
            slippage=slippage,
        )
