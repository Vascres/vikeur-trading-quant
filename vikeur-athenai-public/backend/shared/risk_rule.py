"""Contrat RiskRule (Phase 2, §4.6 ; Phase 13, §6).

Chaque règle est indépendante et testable en isolation. Contrairement à
Feature/Strategy, une règle de risque a légitimement besoin d'un contexte
riche (portefeuille, carnet, capital) - ce contexte est assemblé par
l'appelant (risk_engine/main.py) et injecté, jamais requêté directement
par la règle elle-même (la règle reste pure une fois le contexte fourni).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from shared.strategy import Side


@dataclass
class RiskContext:
    decision_id: int
    exchange: str
    symbol: str
    suggested_side: Side
    success_probability: float
    expected_value: float
    risk_reward_ratio: float

    available_capital: Decimal
    current_price: Decimal
    current_exposure_notional: Decimal
    daily_realized_pnl: Decimal
    consecutive_losses: int

    order_book_bids: list[tuple[Decimal, Decimal]] = field(default_factory=list)
    order_book_asks: list[tuple[Decimal, Decimal]] = field(default_factory=list)

    kill_switch_active: bool = False

    # ADR-0018 : gouverne quelles règles s'appliquent - 'spot' (défaut,
    # comportement inchangé) ou 'futures_perpetual'. Jamais déduit d'une
    # heuristique, toujours fourni explicitement par l'appelant
    # (risk_engine/main.py) à partir de la décision évaluée.
    market_type: str = "spot"

    # Rempli par l'appelant à partir de `positions` (Phase 15, §4) - permet
    # à SpotNoShortingRule de bloquer une vente sans position à clôturer.
    open_position_quantity: Decimal = Decimal("0")

    # Rempli par PositionSizingRule, lu par les règles suivantes (Phase 13, §6)
    suggested_quantity: Decimal | None = None

    # Correctif du 19/08/2026 (question légitime soulevée par
    # l'opérateur : "3 pertes consécutives, puis de belles occasions se
    # présentent - je suis obligé de les rater ?") - pire qu'une simple
    # occasion ratée : sans expiration dans le temps, la pause ne pouvait
    # JAMAIS se lever d'elle-même si aucune position n'était ouverte au
    # moment où le seuil se déclenchait (rien à clôturer -> rien ne peut
    # jamais rompre la série -> blocage définitif). Instant de clôture
    # de la perte la PLUS RÉCENTE de la série en cours - None si aucune
    # perte consécutive active. Lu par `MaxConsecutiveLossRule` pour
    # expirer la pause après un délai, même sans nouvelle clôture
    # gagnante.
    most_recent_loss_closed_at: datetime | None = None


@dataclass(frozen=True)
class RiskCheckResult:
    rule_name: str
    passed: bool
    reason: str | None = None


class RiskRule(ABC):
    rule_name: str

    @abstractmethod
    def check(self, context: RiskContext) -> RiskCheckResult:
        raise NotImplementedError
