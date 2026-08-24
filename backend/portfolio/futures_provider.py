"""Fournisseur de solde futures (17/08/2026) - trou fonctionnel découvert
en répondant à une demande frontend ("je ne vois pas le capital live de
mon compte Binance Future") : aucun `FuturesExchangeAdapter` n'avait
jamais eu de méthode de solde, et `portfolio/main.py` ne construisait de
fournisseur que pour les exchanges spot (`build_exchange_adapter`,
jamais `build_futures_exchange_adapter`). La Live Vault du frontend n'a
donc jamais pu afficher un compte futures, quel que soit l'exchange.

Implémente le MÊME contrat `PortfolioProvider` que `GenericPortfolioProvider`
(spot) - `portfolio/main.py` traite les deux de façon interchangeable
dans sa boucle de snapshot, seul `market_type` distingue les instantanés
qui en résultent.

Ne fonctionne que pour un adaptateur satisfaisant `SupportsAccountBalance`
(`shared/futures_adapter.py`) - vérifié via `isinstance` par l'appelant
avant construction, jamais supposé disponible pour tout exchange futures
(HTX Futures ne l'implémente pas encore, endpoint jamais vérifié avec
la même certitude que Binance).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

import asyncpg

from shared.futures_adapter import SupportsAccountBalance
from shared.portfolio_provider import PortfolioProvider, PortfolioSnapshot

logger = logging.getLogger(__name__)

REFERENCE_CURRENCY = "USDT"


class FuturesPortfolioProvider(PortfolioProvider):
    def __init__(self, exchange_name: str, adapter: SupportsAccountBalance, db_pool: asyncpg.Pool) -> None:
        self.exchange_name = exchange_name
        self._adapter = adapter
        self._db_pool = db_pool

    async def get_balances(self) -> dict[str, Decimal]:
        return await self._adapter.get_account_balance()

    async def take_snapshot(self) -> PortfolioSnapshot:
        balances = await self.get_balances()

        # Simplification assumée, documentée (contrairement au spot,
        # `GenericPortfolioProvider`, qui convertit chaque actif via le
        # dernier prix connu) : un compte futures USDⓈ-M n'a
        # normalement qu'un seul actif de marge pertinent (USDT) -
        # tout autre actif présent (rare, ex. BNB pour les frais) est
        # visible dans `balances` mais exclu du total valorisé, comme
        # pour le spot quand aucun prix suivi n'existe pour un actif.
        total = balances.get(REFERENCE_CURRENCY, Decimal("0"))
        for asset, amount in balances.items():
            if asset != REFERENCE_CURRENCY and amount != 0:
                logger.warning(
                    "Actif futures %s (%s) sur %s exclu du total valorisé - "
                    "seul %s est agrégé pour un compte futures (limitation assumée).",
                    asset,
                    amount,
                    self.exchange_name,
                    REFERENCE_CURRENCY,
                )

        # Correctif du 19/08/2026 (même bug que GenericPortfolioProvider,
        # cf. sa docstring - `balances` contient des actifs à solde nul
        # jamais filtrés avant persistance).
        nonzero_balances = {asset: amount for asset, amount in balances.items() if amount != 0}

        return PortfolioSnapshot(
            exchange=self.exchange_name,
            taken_at=datetime.now(tz=UTC),
            reference_currency=REFERENCE_CURRENCY,
            total_value_reference_currency=total,
            balances=nonzero_balances,
            market_type="futures_perpetual",
        )
