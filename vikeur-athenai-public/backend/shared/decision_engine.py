"""Contrat DecisionEngine (ADR-0002, ADR-0010 ; API Contracts Spec §3).

Remplace `shared/strategy.py` (déprécié, conservé pour référence
historique). Différence essentielle : un moteur individuel ne produit
plus jamais de probabilité - seulement un `score` brut et une
`confidence` déclarée. La conversion en probabilité statistiquement
calibrée est la responsabilité exclusive du méta-moteur
(`meta_engine/`) et de la couche de calibration (ADR-0009), jamais
celle d'un moteur individuel.

Même exigence de pureté que Feature/Strategy : aucun accès réseau,
horloge, ou état externe dans `evaluate()`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from shared.side import Side

__all__ = ["Side", "EngineMetadata", "EngineOpinion", "DecisionEngine"]


@dataclass(frozen=True)
class EngineMetadata:
    name: str
    version: int
    description: str
    # Régimes dans lesquels ce moteur est autorisé à produire un avis
    # (ADR-0011) - ensemble vide = aucune restriction (comportement par
    # défaut, rétrocompatible : aucun moteur existant n'est affecté).
    # Valeurs possibles : cf. regime_engine.detector.detect_regime.
    allowed_regimes: frozenset[str] = field(default_factory=frozenset)
    # Marché visé par ce moteur (chantier de routage par market_type,
    # 16/08/2026) - "spot" par défaut, comportement inchangé pour les 3
    # moteurs directionnels déjà actifs. `decision_engine/main.py` fusionne
    # séparément les avis par market_type (jamais un avis spot fusionné
    # avec un avis futures dans la même décision - deux instruments
    # différents, deux moteurs d'exécution différents) ; la
    # `meta_decision`/`decision` résultante porte explicitement ce
    # market_type, qui prend le pas sur l'heuristique historique de
    # `risk_engine.determine_market_type` (ADR-0019) plutôt que de la
    # contourner silencieusement.
    market_type: str = "spot"


@dataclass(frozen=True)
class EngineOpinion:
    suggested_side: Side
    score: float  # signal brut, PAS une probabilité (cf. docstring de module)
    confidence: float  # dans [0, 1] - confiance du moteur en son propre avis
    uncertainty: float  # grandeur homogène à un risque (ex. volatilité) - jamais 0 ni négative
    rationale: dict = field(default_factory=dict)  # features utilisées - traçabilité (Phase 4 §7)


class DecisionEngine(ABC):
    metadata: EngineMetadata

    @abstractmethod
    def evaluate(self, features: dict[str, float]) -> EngineOpinion | None:
        """Retourne un avis, ou None si les conditions ne sont pas réunies
        (donnée insuffisante, pas de signal clair) - jamais d'exception
        pour une absence de signal, qui est un résultat normal et
        attendu (principe directeur 2 de l'architecture cible)."""
        raise NotImplementedError
