"""Taux de financement réel mesuré (ADR-0020) - complète le manque
laissé explicitement ouvert par ADR-0018 §3.4/§Évolutions futures.

Différence assumée avec `fee_schedule` (ADR-0016) : aucun repli
documenté n'a de sens ici - un funding peut être positif ou négatif,
aucune valeur par défaut ne serait "prudente" (cf. migration
`0018_funding_measurements`). `source` ne prend donc en pratique que la
valeur `MEASURED_API` - un échec de mesure n'insère aucune ligne
plutôt que d'inventer une valeur.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

MEASURED_API = "measured_api"


@dataclass(frozen=True)
class FundingRate:
    exchange: str
    symbol: str  # canonique, ex. "BTC/USDT"
    funding_rate_bps: float  # par période de financement HTX (8h), pas annualisé
    source: str
    measured_at: datetime
