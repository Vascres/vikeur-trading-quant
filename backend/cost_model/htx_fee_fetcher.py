"""Interroge le palier tarifaire réel du compte HTX (ADR-0016).

Utilise les taux "actuels" (`actualMakerRate`/`actualTakerRate`, qui
tiennent compte des remises VIP/jeton natif éventuelles) plutôt que les
taux de base (`makerFeeRate`/`takerFeeRate`) quand ils sont présents -
c'est le coût réellement payé par le compte, pas le tarif affiché.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from cost_model.fee_schedule import MEASURED_API, FeeSchedule, documented_fallback_schedule
from data_collector.adapters.htx import HTXAdapter
from shared.symbol_mapping import canonical_to_native

logger = logging.getLogger(__name__)


def _parse_rate(entry: dict, base_key: str, actual_key: str) -> float:
    """Préfère le taux réel (post-remise) au taux de base, si HTX le fournit."""
    raw = entry.get(actual_key) if entry.get(actual_key) is not None else entry.get(base_key)
    return float(raw) * 10_000  # HTX renvoie une fraction (0.002), converti en bps (20.0)


async def fetch_htx_fee_schedule(adapter: HTXAdapter, canonical_symbols: list[str]) -> list[FeeSchedule]:
    """Retourne un `FeeSchedule` mesuré par symbole - ou un repli documenté,
    par symbole également, si l'appel API échoue (jamais un blocage total
    du service : une panne ponctuelle de cet appel ne doit pas empêcher le
    reste de la plateforme de continuer à fonctionner sur le dernier
    palier mesuré déjà persisté, cf. `cost_model/main.py`)."""
    native_symbols = [canonical_to_native("htx", symbol) for symbol in canonical_symbols]

    try:
        raw_entries = await adapter.get_fee_rate(native_symbols)
    except Exception:
        logger.exception(
            "Échec de la récupération des frais réels HTX - repli documenté "
            "(20 bps/jambe, tarif de base publié) pour ce cycle."
        )
        return [documented_fallback_schedule("htx", symbol) for symbol in canonical_symbols]

    entries_by_native_symbol = {entry["symbol"]: entry for entry in raw_entries}

    schedules = []
    for canonical_symbol, native_symbol in zip(canonical_symbols, native_symbols, strict=True):
        entry = entries_by_native_symbol.get(native_symbol)
        if entry is None:
            logger.warning(
                "Aucune donnée de frais retournée par HTX pour %s - repli documenté.", canonical_symbol
            )
            schedules.append(documented_fallback_schedule("htx", canonical_symbol))
            continue

        schedules.append(
            FeeSchedule(
                exchange="htx",
                symbol=canonical_symbol,
                maker_fee_bps=_parse_rate(entry, "makerFeeRate", "actualMakerRate"),
                taker_fee_bps=_parse_rate(entry, "takerFeeRate", "actualTakerRate"),
                source=MEASURED_API,
                measured_at=datetime.now(tz=UTC),
            )
        )
    return schedules
