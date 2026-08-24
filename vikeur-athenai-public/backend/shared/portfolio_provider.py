"""Contrat PortfolioProvider (ADR-0003, ADR-0007 ; API Contracts Spec §2).

Seule porte d'entrée autorisée vers l'état réel du capital sur un
exchange. `risk_engine` ne doit plus jamais lire une constante de
configuration (`STARTING_CAPITAL`, supprimée) pour connaître le capital
disponible - il consulte exclusivement le dernier `portfolio_snapshots`
produit par le service `portfolio_aggregator` à partir d'une
implémentation de ce contrat (cf. Domain Model Spec, entité Portfolio).

Comme `Feature`/`Strategy`, ce contrat vise un usage sans effet de bord
caché en dehors des deux méthodes définies : aucune écriture en base ne
doit avoir lieu à l'intérieur d'une implémentation de `PortfolioProvider`
elle-même - c'est la responsabilité de l'appelant (`portfolio/main.py`).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class PortfolioSnapshot:
    """Instantané valorisé du portefeuille - correspond à l'entité
    `Portfolio` du modèle de domaine. Immuable par construction : chaque
    appel à `take_snapshot()` produit un nouvel objet, jamais une mise à
    jour d'un précédent."""

    exchange: str
    taken_at: datetime
    reference_currency: str
    total_value_reference_currency: Decimal
    balances: dict[str, Decimal] = field(default_factory=dict)  # actif -> montant
    # Solde de marge futures (17/08/2026) - "spot" par défaut, comportement
    # inchangé pour tout appelant existant. `portfolio/main.py` insère
    # explicitement "futures_perpetual" pour un `FuturesPortfolioProvider`
    # (cf. sa docstring : jamais confondu avec le solde spot par les
    # nombreux lecteurs de `portfolio_snapshots` qui dimensionnent du
    # capital réel - risk_engine, pair_execution, execution_mode_governance,
    # strategy_lifecycle, tous explicitement filtrés sur ce champ).
    market_type: str = "spot"


class PortfolioProvider(ABC):
    exchange_name: str

    @abstractmethod
    async def get_balances(self) -> dict[str, Decimal]:
        """Solde par actif, tel que rapporté par l'exchange.

        Limitation assumée (documentée et non silencieuse, ADR-0007) :
        cette V1 n'agrège que les soldes disponibles au trading, pas les
        montants bloqués dans des ordres ouverts - cohérent avec
        l'implémentation actuelle de `HTXAdapter.get_balances()`
        (Phase 12), à corriger avant toute activation du mode Live.
        """
        raise NotImplementedError

    @abstractmethod
    async def take_snapshot(self) -> PortfolioSnapshot:
        """Convertit `get_balances()` en un instantané valorisé dans la
        devise de référence. Ne persiste rien - la persistance est de la
        responsabilité de l'appelant (`portfolio/main.py`)."""
        raise NotImplementedError
