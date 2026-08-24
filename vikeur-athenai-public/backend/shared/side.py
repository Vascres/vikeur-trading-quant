"""Côté d'une position - BUY/SELL (Phase 2, §6).

Extrait en un module neutre plutôt que dupliqué entre `shared/strategy.py`
(déprécié, ADR-0010) et `shared/decision_engine.py` (contrat actuel) -
corrige une incohérence de typage introduite par erreur lors de la
migration du chantier 4 (deux énumérations identiques mais de classes
différentes, rejetée par mypy à raison : `RiskContext.suggested_side`
ne pouvait accepter qu'une seule des deux).
"""

from enum import Enum


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"
