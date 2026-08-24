"""Contrat FuturesExchangeAdapter (ADR-0018).

Parallèle délibéré à `ExchangeAdapter` (Phase 2, §6), pas une extension
de celui-ci : sur la plupart des exchanges (HTX compris), les contrats
perpétuels utilisent une API entièrement distincte (base URL, format de
compte, authentification parfois partagée mais surface fonctionnelle
différente - positions longues/courtes, taux de financement, marge).
Forcer une seule interface aurait masqué une différence réelle, pas
simplifié quoi que ce soit (ADR-0018 §3.1).

Réutilise volontairement ce qui n'a pas de raison de changer : mapping
de symboles (`shared/symbol_mapping.py`), et pour HTX spécifiquement, le
même schéma de signature HMAC déjà écrit et testé pour l'API spot
(`data_collector/adapters/htx.py::_sign_request`) - la méthode
d'authentification Huobi/HTX est documentée comme partagée entre tous
ses produits (spot, futures, swaps), seule l'hôte cible change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Protocol, runtime_checkable


class PositionSide(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True)
class FuturesPosition:
    symbol: str  # canonique, ex. "BTC/USDT"
    side: PositionSide
    quantity: Decimal
    entry_price: Decimal
    mark_price: Decimal
    unrealized_pnl: Decimal


@runtime_checkable
class SupportsAccountBalance(Protocol):
    """Capacité optionnelle (solde de marge futures, 17/08/2026) -
    délibérément séparée du contrat `FuturesExchangeAdapter`, même
    principe que `SupportsConditionalOrders` : l'endpoint de solde HTX
    Futures n'a jamais été vérifié avec la même certitude que Binance
    (`GET /fapi/v3/balance`, vérifié le 17/08/2026 contre la
    documentation Binance Open Platform) - l'imposer à
    `HTXFuturesAdapter` sans cette vérification serait exactement le
    type de supposition que ce projet interdit.

    `portfolio/main.py` vérifie `isinstance(adapter,
    SupportsAccountBalance)` avant de tenter un instantané de solde
    futures - un exchange qui ne l'implémente pas est simplement exclu
    du solde futures, jamais une erreur silencieuse."""

    async def get_account_balance(self) -> dict[str, Decimal]:
        """Solde par actif du COMPTE FUTURES (distinct du compte spot,
        `ExchangeAdapter.get_balances()`) - même contrat de retour
        (actif -> montant) pour rester réutilisable par
        `GenericPortfolioProvider` sans code dédié."""
        ...


class FuturesExchangeAdapter(ABC):
    """Contrat commun à toute intégration de contrats perpétuels
    (ADR-0018) - permet d'en ajouter d'autres (Binance futures, etc.)
    sans jamais modifier `decision_engine`/`risk_engine`/`execution_engine`,
    même principe d'extensibilité que `ExchangeAdapter` (Phase 1)."""

    exchange_name: str

    def __init__(self, api_key: str | None = None, api_secret: str | None = None) -> None:
        self._api_key = api_key
        self._api_secret = api_secret

    @abstractmethod
    async def get_positions(self, symbol: str) -> list[FuturesPosition]:
        """Positions futures ouvertes pour ce symbole - vide si aucune."""
        raise NotImplementedError

    @abstractmethod
    async def place_order(self, symbol: str, side: PositionSide, quantity: Decimal) -> str:
        """Ouvre ou augmente une position dans le sens `side`. Retourne
        l'identifiant d'ordre exchange. `quantity` est déjà dimensionnée
        par le Risk Engine (`FuturesNotionalExposureCapRule`, ADR-0018) -
        cette méthode ne fait aucune vérification de taille, seulement
        l'exécution."""
        raise NotImplementedError

    @abstractmethod
    async def close_position(self, symbol: str, side: PositionSide, quantity: Decimal) -> str:
        """Clôture (totalement ou partiellement) une position existante."""
        raise NotImplementedError

    @abstractmethod
    async def get_funding_rate(self, symbol: str) -> Decimal:
        """Taux de financement courant (ADR-0018 §3.4) - mesure réelle
        différée à un chantier suivant ; les implémentations concrètes
        d'aujourd'hui peuvent lever `NotImplementedError` explicitement
        plutôt que de retourner une valeur inventée, tant que ce chantier
        de mesure n'est pas fait."""
        raise NotImplementedError

    async def close(self) -> None:
        """Libère les ressources réseau - à surcharger si nécessaire,
        pas obligatoire (comportement par défaut : rien à fermer)."""
        return None


@runtime_checkable
class SupportsConditionalOrders(Protocol):
    """Capacité optionnelle (triptyque d'ordres, mandat §9, 16/08/2026) -
    délibérément SÉPARÉE du contrat `FuturesExchangeAdapter` ci-dessus,
    pas une méthode abstraite supplémentaire dessus : la mécanique
    d'ordres conditionnels HTX Futures n'a jamais été vérifiée contre sa
    documentation (contrairement à Binance, cf. `data_collector/
    adapters/binance_futures.py`) - l'imposer à `HTXFuturesAdapter` sans
    cette vérification serait exactement le type de suppposition que ce
    projet interdit.

    `execution_engine/modes/real.py` vérifie `isinstance(adapter,
    SupportsConditionalOrders)` (typage structurel `Protocol`, aucun
    lien d'héritage requis) avant de tenter de poser un stop-loss
    automatique - un adaptateur qui ne l'implémente pas est traité
    explicitement comme "aucun filet de sécurité disponible", jamais
    silencieusement ignoré (journalisé bruyamment)."""

    async def place_stop_loss(self, symbol: str, position_side: PositionSide, stop_price: Decimal) -> str:
        """Pose un ordre STOP_MARKET qui ferme toute la position au
        marché si le prix atteint `stop_price` - jamais un ordre
        partiel (mandat §8 : "Le Risk Engine refuse d'être liquidé par
        l'exchange"). Retourne l'identifiant d'ordre exchange."""
        ...

    async def cancel_order(self, symbol: str, order_id: str) -> None:
        """Annule un ordre encore ouvert (typiquement le stop-loss
        restant une fois la position fermée par une autre voie - agent
        ou take-profit) - jamais laissé traîner sur l'exchange."""
        ...
