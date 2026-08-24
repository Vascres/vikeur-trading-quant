"""Frais réels mesurés (ADR-0016, CostModel) - remplace la constante
`ASSUMED_ROUND_TRIP_FEE_BPS` (Phase 13) qui n'a jamais été mesurée.

Diagnostic ayant motivé ce chantier : recherche publique menée avant
implémentation - le tarif spot HTX standard (palier non-VIP, "Prime 0")
est de 0,20 % maker ET taker, soit 40 bps l'aller-retour au palier de
base - le double de la constante précédemment codée (20 bps). Les
paliers VIP réduisent ce tarif avec le volume - impossible à connaître
sans interroger le compte réel, d'où ce module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from shared.fee_constants import (
    DOCUMENTED_FALLBACK,
    DOCUMENTED_FALLBACK_BINANCE_SPOT_TAKER_FEE_BPS,
    DOCUMENTED_FALLBACK_TAKER_FEE_BPS,
    MEASURED_API,  # noqa: F401 - ré-exporté pour cost_model/htx_fee_fetcher.py et binance_fee_fetcher.py
)

# Chantier CostModel unique (16/08/2026) : un repli documenté par
# exchange, jamais un seul tarif HTX appliqué par erreur à un autre
# exchange (piège découvert en écrivant ce module : avant cette table,
# `documented_fallback_schedule("binance", ...)` aurait silencieusement
# utilisé le tarif HTX). Étendre à un futur exchange = ajouter une ligne
# ici, jamais modifier la fonction.
_DOCUMENTED_FALLBACK_TAKER_FEE_BPS_BY_EXCHANGE: dict[str, float] = {
    "htx": DOCUMENTED_FALLBACK_TAKER_FEE_BPS,
    "binance": DOCUMENTED_FALLBACK_BINANCE_SPOT_TAKER_FEE_BPS,
}


@dataclass(frozen=True)
class FeeSchedule:
    exchange: str
    symbol: str  # symbole canonique, ex. "BTC/USDT"
    maker_fee_bps: float
    taker_fee_bps: float
    source: str  # MEASURED_API | DOCUMENTED_FALLBACK
    measured_at: datetime

    @property
    def round_trip_taker_fee_bps(self) -> float:
        """Coût round-trip (achat + vente) si les deux jambes sont exécutées
        en taker - l'hypothèse la plus réaliste pour des moteurs qui
        réagissent à un signal de momentum (pas le temps d'attendre un
        remplissage en maker, cf. étude CostModel §1)."""
        return self.taker_fee_bps * 2


def documented_fallback_schedule(exchange: str, symbol: str) -> FeeSchedule:
    """Repli utilisé uniquement si l'API de frais réels est injoignable -
    jamais au démarrage normal. Toujours étiqueté `DOCUMENTED_FALLBACK`,
    jamais confondu avec `MEASURED_API` côté consommateurs (`decision_engine`,
    `risk_engine`) ni côté explicabilité (`/decisions/{id}/explain`).

    Le tarif de repli dépend de l'exchange (cf.
    `_DOCUMENTED_FALLBACK_TAKER_FEE_BPS_BY_EXCHANGE`) - un exchange non
    encore répertorié retombe sur le tarif HTX plutôt que de lever une
    exception, pour ne jamais bloquer un cycle de mesure sur un détail
    de configuration ; à corriger en ajoutant l'entrée manquante, jamais
    en supposant silencieusement HTX à long terme."""
    fallback_bps = _DOCUMENTED_FALLBACK_TAKER_FEE_BPS_BY_EXCHANGE.get(
        exchange, DOCUMENTED_FALLBACK_TAKER_FEE_BPS
    )
    return FeeSchedule(
        exchange=exchange,
        symbol=symbol,
        maker_fee_bps=fallback_bps,
        taker_fee_bps=fallback_bps,
        source=DOCUMENTED_FALLBACK,
        measured_at=datetime.now(tz=UTC),
    )
