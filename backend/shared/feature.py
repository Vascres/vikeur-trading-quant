"""Contrat Feature (Phase 2, §6).

Une feature est une fonction pure : mêmes données en entrée -> toujours le
même résultat. C'est la condition de reproductibilité des backtests
(Phase 4, §5.2) et le fondement du mécanisme de versionnement par hash
de code (Phase 9, §3).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureMetadata:
    name: str
    version: int
    description: str


class Feature(ABC):
    """Toute feature du feature_engine doit hériter de cette classe.

    `compute` ne doit JAMAIS accéder au réseau, à l'horloge système, ou à
    tout état mutable externe - uniquement aux données passées en argument.
    C'est ce qui garantit la reproductibilité (Phase 4 §5.2, Phase 9 §3).
    """

    metadata: FeatureMetadata

    @abstractmethod
    def compute(self, market_data: dict) -> float | None:
        """Calcule la valeur de la feature à partir des données fournies.

        Retourne None si la donnée est insuffisante (ex. pas assez de
        périodes d'historique) plutôt que de lever une exception - une
        feature manquante ne doit jamais interrompre le pipeline complet.
        """
        raise NotImplementedError
