"""Mode Backtest (Phase 12, §4).

Ne fait AUCUN accès réseau - le prix est fourni par l'appelant (le moteur
de backtest, Phase 14, qui rejoue l'historique). Modèle de coûts simple et
explicite, volontairement pas plus sophistiqué que ça en V1 - à calibrer
avec des données réelles en Phase 14.
"""

from decimal import Decimal

import asyncpg

from execution_engine.common import insert_order_row
from shared.execution_mode import ExecutionMode, OrderResult

# Valeurs de départ, non calibrées (Phase 12, §7 - à ajuster en Phase 14)
ASSUMED_SLIPPAGE_BPS = Decimal("5")
ASSUMED_FEE_BPS = Decimal("10")


class BacktestExecutionMode(ExecutionMode):
    mode_name = "backtest"

    def __init__(self, db_pool: asyncpg.Pool) -> None:
        self._db_pool = db_pool

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
        # ADR-0019 : `market_type` non utilisé ici - le backtest gère son
        # état en mémoire (BacktestPortfolio), sans jamais toucher
        # `positions`, donc rien à router par type de marché pour l'instant.
        if price is None:
            raise ValueError("Le mode backtest nécessite un prix historique explicite (Phase 12, §4).")

        cost_bps = ASSUMED_SLIPPAGE_BPS + ASSUMED_FEE_BPS
        direction = 1 if side == "buy" else -1
        filled_price = price * (1 + direction * cost_bps / Decimal(10_000))
        slippage = abs(filled_price - price)

        order_id = await insert_order_row(
            self._db_pool,
            risk_check_id=risk_check_id,
            exchange=exchange,
            symbol=symbol,
            side=side,
            execution_mode=self.mode_name,
            requested_price=price,
            requested_quantity=quantity,
            filled_price=filled_price,
            filled_quantity=quantity,
            slippage=slippage,
            status="filled",
        )

        return OrderResult(
            order_id=str(order_id),
            status="filled",
            filled_price=filled_price,
            filled_quantity=quantity,
            slippage=slippage,
        )
