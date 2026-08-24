"""Implémentation Binance du contrat PortfolioProvider (ADR-0012).

Ne fait que fixer `exchange_name="binance"` sur `GenericPortfolioProvider`
- la logique de valorisation elle-même est partagée avec HTX, jamais
dupliquée (cf. `portfolio/generic_provider.py`).
"""

from __future__ import annotations

import asyncpg

from data_collector.adapters.binance import BinanceAdapter
from portfolio.generic_provider import GenericPortfolioProvider


class BinancePortfolioProvider(GenericPortfolioProvider):
    def __init__(self, binance_adapter: BinanceAdapter, db_pool: asyncpg.Pool) -> None:
        super().__init__(exchange_name="binance", adapter=binance_adapter, db_pool=db_pool)
