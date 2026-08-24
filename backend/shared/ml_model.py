"""Contrat MLModel (Phase 16, §4).

Contrairement à Feature/Strategy, un modèle ML n'est pas une fonction pure
figée par un hash de code - c'est un artefact entraîné. La reproductibilité
vient d'ailleurs : mêmes données d'entraînement (features versionnées,
Phase 9) + même algorithme + graine aléatoire fixée.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class MLModelMetadata:
    name: str
    algorithm: str


class MLModel(ABC):
    metadata: MLModelMetadata

    @abstractmethod
    def fit(self, X: list[list[float]], y: list[int]) -> None:
        raise NotImplementedError

    @abstractmethod
    def predict_proba(self, X: list[list[float]]) -> list[float]:
        """Retourne la probabilité de la classe positive (hausse) pour chaque ligne."""
        raise NotImplementedError

    @abstractmethod
    def serialize(self) -> bytes:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def deserialize(cls, data: bytes) -> "MLModel":
        raise NotImplementedError
