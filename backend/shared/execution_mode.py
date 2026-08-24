"""Contrat ExecutionMode (Phase 2, §4.7).

Les 3 modes (backtest/paper/réel) implémentent EXACTEMENT la même
interface, pour garantir que le Moteur de décision et le Moteur de
risque n'ont aucune connaissance du mode actif (Phase 1 : "ce qui est
testé est bien ce qui tourne en réel").
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class OrderResult:
    order_id: str
    status: str  # 'pending' | 'filled' | 'partially_filled' | 'cancelled' | 'rejected'
    filled_price: Decimal | None
    filled_quantity: Decimal | None
    slippage: Decimal | None


class ExecutionMode(ABC):
    mode_name: str  # 'backtest' | 'paper' | 'real' - doit correspondre à orders.execution_mode (Phase 6)

    @abstractmethod
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
        """Exécute (ou simule) un ordre déjà validé par le Moteur de risque.

        `risk_check_id` doit référencer une ligne `risk_checks` existante
        et validée (Phase 4 §7, Phase 6). `decision_id` permet d'attribuer
        la position résultante à la stratégie qui l'a produite (Phase 17).

        `market_type` (ADR-0019, défaut `'spot'` - rétrocompatible avec
        tout appelant non mis à jour) : `'spot'` ou `'futures_perpetual'` -
        déjà déterminé en amont par le Risk Engine (`RiskContext.market_type`,
        ADR-0018), jamais recalculé ici.
        """
        raise NotImplementedError
