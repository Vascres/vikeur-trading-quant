"""Contrat Strategy (Phase 2, §6).

DÉPRÉCIÉ depuis ADR-0010 - remplacé par `shared/decision_engine.py`
(`DecisionEngine`/`EngineOpinion`), qui sépare score brut et probabilité
calibrée (ADR-0002). Conservé tel quel pour référence historique ; aucun
code actif ne l'importe plus (vérifié par `importlinter`, contrat 5,
inchangé - `strategies` n'a jamais eu le droit d'importer les couches
aval, ce qui reste vrai pour son successeur).

Une stratégie combine des features déjà calculées en une proposition
de position évaluée (probabilité, espérance, ratio rendement/risque).
Même exigence de pureté que Feature (Phase 9) : aucun accès réseau,
horloge, ou état externe dans `evaluate()`.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from shared.side import Side

__all__ = ["Side", "StrategyMetadata", "StrategyProposal", "Strategy"]


@dataclass(frozen=True)
class StrategyMetadata:
    name: str
    version: int
    description: str


@dataclass(frozen=True)
class StrategyProposal:
    suggested_side: Side
    success_probability: float  # dans [0, 1]
    expected_value: float
    risk_reward_ratio: float
    rationale: dict = field(default_factory=dict)  # features utilisées - traçabilité (Phase 4 §7)


class Strategy(ABC):
    metadata: StrategyMetadata

    @abstractmethod
    def evaluate(self, features: dict[str, float]) -> StrategyProposal | None:
        """Retourne une proposition, ou None si les conditions ne sont pas réunies
        (donnée insuffisante, pas de signal clair) - jamais d'exception pour un
        cas d'absence de signal, qui est un résultat normal et attendu (Phase 1,
        §3 : "le moteur devra pouvoir rester inactif pendant plusieurs heures").
        """
        raise NotImplementedError
