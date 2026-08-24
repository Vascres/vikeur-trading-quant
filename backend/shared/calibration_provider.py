"""Contrat CalibrationProvider (ADR-0009 ; API Contracts Spec §5).

Convertit un score brut en probabilité statistiquement calibrée. C'est
la SEULE entité du système autorisée à produire une probabilité qui
mérite le nom `success_probability` - un `DecisionEngine` individuel ne
produit qu'un `score` non calibré (cf. `shared/governance_check.py` et
ADR-0002 pour le principe de séparation).

Interim (ADR-0009) : tant que le méta-moteur (chantier 4) n'existe pas,
la donnée d'entrée reste `decisions.success_probability` (le score brut
de l'unique stratégie existante) plutôt que le score fusionné visé à
terme - seul le point de branchement changera, jamais ce contrat.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np


@dataclass(frozen=True)
class CalibrationRun:
    method: str
    computed_at: datetime
    sample_size: int
    is_validated: bool

    training_period_start: datetime | None = None
    training_period_end: datetime | None = None
    brier_score: float | None = None

    # Paramètres ajustés (ex. intercept/coefficient pour une régression
    # logistique) - opaques pour l'appelant, propres à chaque méthode.
    parameters: dict = field(default_factory=dict)

    # Explique pourquoi la calibration n'est pas validée, le cas échéant
    # (échantillon insuffisant, Brier score trop élevé...) - jamais un
    # rejet silencieux (principe directeur 1).
    reason: str | None = None


def apply_logistic_parameters(calibration: CalibrationRun, raw_score: float) -> float:
    """Applique `sigmoid(intercept + coefficient * raw_score)`.

    Factorisé ici (ADR-0015) car `LogisticCalibrationProvider` (ADR-0009)
    et `BayesianCalibrationProvider` (ADR-0015) partagent exactement la
    même formule d'application - seule la façon dont `intercept`/
    `coefficient` sont *estimés* diffère entre les deux méthodes. Éviter
    de dupliquer cette formule suit le même principe déjà appliqué à
    `meta_engine/cost_estimation.py` (ADR-0010), salué par l'audit
    initial de la plateforme.
    """
    intercept = calibration.parameters["intercept"]
    coefficient = calibration.parameters["coefficient"]
    z = intercept + coefficient * raw_score
    return 1.0 / (1.0 + np.exp(-z))


class CalibrationProvider(ABC):
    method_name: str

    @abstractmethod
    async def calibrate(
        self, historical_scores: list[float], historical_outcomes: list[bool]
    ) -> CalibrationRun:
        """`historical_scores`/`historical_outcomes` doivent déjà être
        triés chronologiquement par l'appelant - le découpage
        train/validation à l'intérieur de cette méthode est toujours
        chronologique, jamais aléatoire (Development Standards, cf.
        ml_engine/training_pipeline.py)."""
        raise NotImplementedError

    @abstractmethod
    def apply(self, calibration: CalibrationRun, raw_score: float) -> float:
        """Ne doit jamais être appelée avec une `calibration` dont
        `is_validated` est `False` - c'est la responsabilité de
        l'appelant (le futur méta-moteur) de vérifier ce champ avant
        d'appeler `apply()`."""
        raise NotImplementedError
