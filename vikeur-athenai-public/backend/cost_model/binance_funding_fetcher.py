"""Interroge le funding réel Binance USDⓈ-M Futures, symbole par symbole
(Étapes 7-8 du plan validé le 16/08/2026 - étend ADR-0020 à un second
exchange futures).

Miroir de `cost_model/htx_funding_fetcher.py`, jamais généralisé en une
fonction unique paramétrée par exchange : le fetcher HTX existant fixe
`exchange="htx"` en dur dans le `FundingRate` produit (pas déduit de
l'adaptateur reçu) - le généraliser aurait été un changement de contrat
plus large que ce chantier, pas une simple duplication. Même discipline
d'échec que HTX : aucun repli documenté n'a de sens pour le funding, un
symbole en échec est simplement omis, jamais une valeur inventée.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from cost_model.funding_rate import MEASURED_API, FundingRate
from shared.futures_adapter import FuturesExchangeAdapter

logger = logging.getLogger(__name__)


async def fetch_binance_funding_rates(
    adapter: FuturesExchangeAdapter, canonical_symbols: list[str]
) -> list[FundingRate]:
    rates: list[FundingRate] = []
    for symbol in canonical_symbols:
        try:
            raw_rate = await adapter.get_funding_rate(symbol)
        except Exception:
            logger.exception(
                "Échec de la récupération du funding Binance pour %s - omis pour ce cycle "
                "(aucun repli inventé, ADR-0020).",
                symbol,
            )
            continue

        rates.append(
            FundingRate(
                exchange="binance",
                symbol=symbol,
                funding_rate_bps=float(raw_rate) * 10_000,  # fraction par période -> bps par période
                source=MEASURED_API,
                measured_at=datetime.now(tz=UTC),
            )
        )
    return rates
