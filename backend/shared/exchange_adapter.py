"""Contrat ExchangeAdapter (Phase 2, §6).

Toute intégration d'exchange doit respecter cette interface, pour permettre
d'en ajouter de nouvelles (Phase 1 - objectif d'extensibilité) sans jamais
modifier le data_collector, le Normalizer, ou tout module en aval.

En Phase 7, seules les méthodes de données de marché publiques sont
implémentées. Les méthodes de trading (place_order, cancel_order,
get_balances) sont définies ici pour fixer le contrat dès maintenant,
mais implémentées réellement en Phase 12 (moteur d'exécution).
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class RawTradeMessage:
    """Message de trade tel que reçu de l'exchange, avant normalisation (Phase 8)."""

    exchange: str
    native_symbol: str
    payload: dict


@dataclass(frozen=True)
class RawOrderBookMessage:
    """Snapshot de carnet d'ordres tel que reçu de l'exchange, avant normalisation."""

    exchange: str
    native_symbol: str
    payload: dict


class ExchangeAdapter(ABC):
    """Contrat commun à tous les exchanges (Phase 2, §6).

    `__init__` est déclaré ici (non abstrait) pour que la fabrique
    (`data_collector/adapters/factory.py`, ADR-0012) puisse construire
    n'importe quel adaptateur enregistré via un type générique
    `type[ExchangeAdapter]` sans erreur de typage - chaque implémentation
    concrète peut toujours étendre la signature si besoin.
    """

    exchange_name: str

    def __init__(
        self,
        journal_publisher: Callable[[str, dict], None] | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
    ) -> None:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Données de marché publiques (implémentées en Phase 7)
    # ------------------------------------------------------------------

    @abstractmethod
    def stream_trades(self, symbols: list[str]) -> AsyncIterator[RawTradeMessage]:
        """Flux continu des trades exécutés sur l'exchange pour les symboles donnés.

        Déclaré sans `async` (bien qu'implémenté par un générateur async,
        `async def ... yield ...`) - convention mypy pour les itérateurs
        asynchrones abstraits, cf. https://mypy.readthedocs.io/en/stable/more_types.html#asynchronous-iterators.
        """
        raise NotImplementedError

    @abstractmethod
    def stream_order_book(self, symbols: list[str]) -> AsyncIterator[RawOrderBookMessage]:
        """Flux continu des snapshots de carnet d'ordres."""
        raise NotImplementedError

    @abstractmethod
    async def fetch_recent_trades(self, symbol: str, limit: int) -> list[RawTradeMessage]:
        """Backfill REST ponctuel (démarrage, resynchronisation après trou détecté)."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Trading (contrat fixé dès la Phase 7, implémentation réelle en Phase 12)
    # ------------------------------------------------------------------

    @abstractmethod
    async def place_order(
        self, symbol: str, side: OrderSide, quantity: Decimal, price: Decimal | None
    ) -> str:
        """Envoie un ordre réel. Implémenté en Phase 12 - lève NotImplementedError ici."""
        raise NotImplementedError("place_order sera implémenté en Phase 12 (moteur d'exécution).")

    @abstractmethod
    async def cancel_order(self, order_id: str) -> None:
        raise NotImplementedError("cancel_order sera implémenté en Phase 12.")

    @abstractmethod
    async def get_balances(self) -> dict[str, Decimal]:
        raise NotImplementedError("get_balances sera implémenté en Phase 12.")

    @abstractmethod
    async def get_order_status(self, order_id: str) -> dict:
        """Retourne au minimum `{"state": ..., "filled_amount": ...}` - le
        vocabulaire de `state` est normalisé par chaque implémentation
        (cf. HTXAdapter/BinanceAdapter) pour rester interchangeable côté
        `RealExecutionMode` (Phase 20, §3). Formalisé dans le contrat par
        ADR-0012 - existait auparavant seulement par convention informelle."""
        raise NotImplementedError("get_order_status sera implémenté en Phase 12/20.")

    @abstractmethod
    async def close(self) -> None:
        """Ferme les connexions (client HTTP, WebSocket) - formalisé dans
        le contrat par ADR-0012, existait auparavant seulement par
        convention informelle."""
        raise NotImplementedError
