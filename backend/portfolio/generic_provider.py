"""Implémentation générique du contrat PortfolioProvider (ADR-0007,
généralisée par ADR-0012).

`HTXPortfolioProvider` et `BinancePortfolioProvider` ne différaient que
par l'exchange et le type d'adaptateur injecté - la logique de
valorisation elle-même (agrégation des soldes, conversion en devise de
référence via les prix déjà collectés) est identique et désormais
partagée ici plutôt que dupliquée deux fois (Development Standards §3).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

import asyncpg

from shared.exchange_adapter import ExchangeAdapter
from shared.portfolio_provider import PortfolioProvider, PortfolioSnapshot

logger = logging.getLogger(__name__)

REFERENCE_CURRENCY = "USDT"


class GenericPortfolioProvider(PortfolioProvider):
    def __init__(self, exchange_name: str, adapter: ExchangeAdapter, db_pool: asyncpg.Pool) -> None:
        self.exchange_name = exchange_name
        self._adapter = adapter
        self._db_pool = db_pool

    async def get_balances(self) -> dict[str, Decimal]:
        return await self._adapter.get_balances()

    async def take_snapshot(self) -> PortfolioSnapshot:
        balances = await self.get_balances()
        total = Decimal("0")

        async with self._db_pool.acquire() as conn:
            for asset, amount in balances.items():
                if amount == 0:
                    continue
                if asset == REFERENCE_CURRENCY:
                    total += amount
                    continue

                price_row = await conn.fetchrow(
                    """
                    SELECT close FROM ohlcv_candles_1m
                    WHERE exchange = $1 AND symbol = $2
                    ORDER BY bucket DESC LIMIT 1;
                    """,
                    self.exchange_name,
                    f"{asset}/{REFERENCE_CURRENCY}",
                )
                if price_row is None:
                    # Limitation assumée (ADR-0007) : un actif détenu sans
                    # paire de prix suivie par la plateforme n'est pas
                    # valorisé - visible dans `balances`, mais absent du
                    # total. Jamais silencieux : journalisé en warning.
                    logger.warning(
                        "Aucun prix suivi pour %s/%s sur %s - actif exclu du total valorisé",
                        asset,
                        REFERENCE_CURRENCY,
                        self.exchange_name,
                    )
                    continue

                total += amount * Decimal(str(price_row["close"]))

        # Correctif du 19/08/2026 (bug réel remontant au 27/07, jamais
        # détecté avant que le disque VPS n'atteigne 98%) : `balances`
        # (issu de `get_balances()`) contient TOUS les actifs connus de
        # l'exchange, y compris des centaines à solde nul - jamais
        # filtré avant d'être persisté dans `portfolio_snapshot_balances`,
        # une ligne par actif par relevé (~1362 lignes/relevé mesurées
        # en production, dont l'écrasante majorité à 0). Une ligne
        # "XRP : 0" n'a aucune valeur analytique - ne jamais la stocker.
        nonzero_balances = {asset: amount for asset, amount in balances.items() if amount != 0}

        return PortfolioSnapshot(
            exchange=self.exchange_name,
            taken_at=datetime.now(tz=UTC),
            reference_currency=REFERENCE_CURRENCY,
            total_value_reference_currency=total,
            balances=nonzero_balances,
        )
