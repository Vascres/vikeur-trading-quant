"""État de portefeuille simulé pour le backtest (Phase 14, §3).

Fonctions pures - aucun accès DB. `BacktestPortfolio` maintient l'état
en mémoire pendant le rejeu (engine.py) ; les tables live ne sont jamais
touchées (Phase 14, §3.1).

Hypothèse V1 : spot long-only (cohérent avec le choix Spot de la Phase 7)
- une position ouverte par symbole au maximum, pas de vente à découvert.
"""

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class OpenPosition:
    entry_time: object  # datetime - typé large pour rester découplé de la DB
    entry_price: Decimal
    quantity: Decimal


@dataclass
class ClosedTrade:
    symbol: str
    side: str
    entry_time: object
    exit_time: object
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    pnl: Decimal


@dataclass
class BacktestPortfolio:
    starting_capital: Decimal
    realized_pnl: Decimal = Decimal("0")
    open_positions: dict[str, OpenPosition] = field(default_factory=dict)
    closed_trades: list[ClosedTrade] = field(default_factory=list)
    equity_curve: list[Decimal] = field(default_factory=list)
    consecutive_losses: int = 0

    @property
    def available_capital(self) -> Decimal:
        return self.starting_capital + self.realized_pnl

    def current_exposure_notional(self, current_prices: dict[str, Decimal]) -> Decimal:
        total = Decimal("0")
        for symbol, position in self.open_positions.items():
            price = current_prices.get(symbol, position.entry_price)
            total += position.quantity * price
        return total

    def open_or_add(self, symbol: str, time, price: Decimal, quantity: Decimal) -> None:
        """Ouvre une position, ou l'agrandit (moyenne pondérée) si déjà ouverte."""
        existing = self.open_positions.get(symbol)
        if existing is None:
            self.open_positions[symbol] = OpenPosition(entry_time=time, entry_price=price, quantity=quantity)
            return

        total_quantity = existing.quantity + quantity
        weighted_price = (existing.entry_price * existing.quantity + price * quantity) / total_quantity
        self.open_positions[symbol] = OpenPosition(
            entry_time=existing.entry_time, entry_price=weighted_price, quantity=total_quantity
        )

    def close(self, symbol: str, time, price: Decimal, quantity: Decimal) -> ClosedTrade | None:
        """Ferme (totalement ou partiellement) une position ouverte. Retourne None si rien à fermer
        (spot long-only : impossible de vendre sans position ouverte - Phase 14, §3)."""
        existing = self.open_positions.get(symbol)
        if existing is None or existing.quantity <= 0:
            return None

        closed_quantity = min(quantity, existing.quantity)
        pnl = (price - existing.entry_price) * closed_quantity

        trade = ClosedTrade(
            symbol=symbol,
            side="sell",
            entry_time=existing.entry_time,
            exit_time=time,
            entry_price=existing.entry_price,
            exit_price=price,
            quantity=closed_quantity,
            pnl=pnl,
        )

        self.realized_pnl += pnl
        self.closed_trades.append(trade)
        self.consecutive_losses = self.consecutive_losses + 1 if pnl < 0 else 0

        remaining = existing.quantity - closed_quantity
        if remaining > 0:
            self.open_positions[symbol] = OpenPosition(
                entry_time=existing.entry_time, entry_price=existing.entry_price, quantity=remaining
            )
        else:
            del self.open_positions[symbol]

        self.equity_curve.append(self.available_capital)
        return trade

    def daily_realized_pnl(self, day) -> Decimal:
        """Somme des PnL des trades fermés le jour donné (comparaison de dates)."""
        return sum(
            (t.pnl for t in self.closed_trades if _same_day(t.exit_time, day)),
            Decimal("0"),
        )


def _same_day(a, b) -> bool:
    return a.date() == b.date() if hasattr(a, "date") and hasattr(b, "date") else a == b
