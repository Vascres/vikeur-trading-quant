"""Interroge le palier tarifaire réel du compte Binance (chantier
CostModel unique, 16/08/2026 - étend ADR-0016 à un second exchange).

Contrairement à HTX (`htx_fee_fetcher.py`), l'endpoint Binance
(`GET /sapi/v1/asset/tradeFee`) renvoie directement le taux effectif du
compte (remises VIP/BNB déjà appliquées) - une seule paire de valeurs
par symbole, aucune distinction taux de base/taux réel à faire ici.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from cost_model.fee_schedule import MEASURED_API, FeeSchedule, documented_fallback_schedule
from data_collector.adapters.binance import BinanceAdapter
from shared.symbol_mapping import canonical_to_native

logger = logging.getLogger(__name__)


async def fetch_binance_fee_schedule(
    adapter: BinanceAdapter, canonical_symbols: list[str]
) -> list[FeeSchedule]:
    """Retourne un `FeeSchedule` mesuré par symbole - ou un repli
    documenté, par symbole également, si l'appel API échoue (même
    discipline que `fetch_htx_fee_schedule` : une panne ponctuelle ne
    doit jamais empêcher le reste de la plateforme de continuer à
    fonctionner sur le dernier palier mesuré déjà persisté)."""
    native_symbols = [canonical_to_native("binance", symbol).upper() for symbol in canonical_symbols]

    try:
        raw_entries = await adapter.get_fee_rate(native_symbols)
    except Exception:
        logger.exception(
            "Échec de la récupération des frais réels Binance - repli documenté "
            "(10 bps/jambe, tarif de base publié) pour ce cycle."
        )
        return [documented_fallback_schedule("binance", symbol) for symbol in canonical_symbols]

    entries_by_native_symbol = {entry["symbol"]: entry for entry in raw_entries}

    schedules = []
    for canonical_symbol, native_symbol in zip(canonical_symbols, native_symbols, strict=True):
        entry = entries_by_native_symbol.get(native_symbol)
        if entry is None:
            logger.warning(
                "Aucune donnée de frais retournée par Binance pour %s - repli documenté.", canonical_symbol
            )
            schedules.append(documented_fallback_schedule("binance", canonical_symbol))
            continue

        schedules.append(
            FeeSchedule(
                exchange="binance",
                symbol=canonical_symbol,
                maker_fee_bps=float(entry["makerCommission"]) * 10_000,
                taker_fee_bps=float(entry["takerCommission"]) * 10_000,
                source=MEASURED_API,
                measured_at=datetime.now(tz=UTC),
            )
        )
    return schedules
