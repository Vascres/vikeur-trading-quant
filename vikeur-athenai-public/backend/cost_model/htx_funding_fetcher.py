"""Interroge le funding réel HTX Futures, symbole par symbole (ADR-0020).

Contrairement à `htx_fee_fetcher.py` (ADR-0016), aucun repli documenté
n'a de sens pour le funding (cf. `cost_model/funding_rate.py`) - un
symbole dont la mesure échoue est simplement omis du résultat de ce
cycle, journalisé, jamais remplacé par une valeur inventée. Une panne
sur un symbole n'empêche jamais la mesure des autres (appel par
symbole, capturé individuellement).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from cost_model.funding_rate import MEASURED_API, FundingRate
from shared.futures_adapter import FuturesExchangeAdapter

logger = logging.getLogger(__name__)


async def fetch_htx_funding_rates(
    adapter: FuturesExchangeAdapter, canonical_symbols: list[str]
) -> list[FundingRate]:
    rates: list[FundingRate] = []
    for symbol in canonical_symbols:
        try:
            raw_rate = await adapter.get_funding_rate(symbol)
        except Exception:
            logger.exception(
                "Échec de la récupération du funding HTX pour %s - omis pour ce cycle "
                "(aucun repli inventé, ADR-0020).",
                symbol,
            )
            continue

        rates.append(
            FundingRate(
                exchange="htx",
                symbol=symbol,
                funding_rate_bps=float(raw_rate) * 10_000,  # fraction par période -> bps par période
                source=MEASURED_API,
                measured_at=datetime.now(tz=UTC),
            )
        )
    return rates
