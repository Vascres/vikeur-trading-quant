"""Implémentation HTX du contrat PortfolioProvider (ADR-0007).

Depuis ADR-0012, ne fait plus que fixer `exchange_name="htx"` sur
`GenericPortfolioProvider` - la logique de valorisation elle-même est
partagée avec Binance (et tout futur exchange), plus dupliquée.
"""

from __future__ import annotations

import asyncpg

from data_collector.adapters.htx import HTXAdapter
from portfolio.generic_provider import GenericPortfolioProvider


class HTXPortfolioProvider(GenericPortfolioProvider):
    def __init__(self, htx_adapter: HTXAdapter, db_pool: asyncpg.Pool) -> None:
        super().__init__(exchange_name="htx", adapter=htx_adapter, db_pool=db_pool)
