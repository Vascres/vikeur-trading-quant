"""Application de la calibration active au score fusionné (ADR-0009,
ADR-0010, ADR-0014, ADR-0015).

Consulte la `calibration_runs` active (chantier 3) - si aucune n'est
seulement au niveau `collecting` du Confidence Lifecycle (ADR-0015,
`shared/confidence_lifecycle.py`), retourne explicitement `None` plutôt
que d'inventer une probabilité par défaut (principe directeur 2 de
l'architecture cible ; invariant déjà posé par `CalibrationProvider`,
API Contracts Spec §5).

Deux fonctions d'application, volontairement distinctes plutôt qu'un
paramètre booléen implicite (le nom de la fonction appelée doit rendre
la garantie visible à l'appel) :
- `apply_calibration_if_valid` (ADR-0009, inchangée) : n'accepte que le
  niveau `validated` - seule autorisée en mode réel (ADR-0014).
- `apply_calibration_if_available` (ADR-0015, nouvelle) : accepte aussi
  le niveau `preliminary` - réservée au mode paper (ADR-0014), jamais
  appelée par le chemin d'exécution réel.
"""

from __future__ import annotations

import json

import asyncpg

from shared.calibration_provider import CalibrationRun, apply_logistic_parameters
from shared.confidence_lifecycle import COLLECTING, classify_calibration_maturity


async def fetch_active_calibration(db_pool: asyncpg.Pool) -> tuple[int, CalibrationRun] | None:
    """Retourne (id en base, CalibrationRun) de la calibration active, ou
    None si aucune n'existe - l'id n'est pas porté par le dataclass
    `CalibrationRun` lui-même (une préoccupation de persistance, pas du
    domaine), donc retourné séparément ici pour alimenter
    `meta_decisions.calibration_run_id`."""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM calibration_runs WHERE is_active ORDER BY computed_at DESC LIMIT 1;"
        )
    if row is None:
        return None

    parameters = row["parameters"]
    if isinstance(parameters, str):
        parameters = json.loads(parameters)

    calibration = CalibrationRun(
        method=row["method"],
        computed_at=row["computed_at"],
        sample_size=row["sample_size"],
        is_validated=row["is_validated"],
        training_period_start=row["training_period_start"],
        training_period_end=row["training_period_end"],
        brier_score=row["brier_score"],
        parameters=dict(parameters),
        reason=row["reason"],
    )
    return row["id"], calibration


def apply_calibration_if_valid(calibration: CalibrationRun | None, fused_score: float) -> float | None:
    """ADR-0009 : n'applique la calibration que si elle est pleinement
    `validated` (Confidence Lifecycle, ADR-0015) - c'est la seule
    fonction autorisée à alimenter une décision en mode réel
    (`decision_engine/main.py`, ADR-0014)."""
    if calibration is None or not calibration.is_validated:
        return None
    return apply_logistic_parameters(calibration, fused_score)


def apply_calibration_if_available(calibration: CalibrationRun | None, fused_score: float) -> float | None:
    """ADR-0015 : applique la calibration dès le niveau `preliminary` du
    Confidence Lifecycle (échantillon >= 5, cf.
    `shared/confidence_lifecycle.py`), pas seulement `validated`.

    Réservée au mode paper (ADR-0014) : permet au système d'accumuler
    l'historique de trades nécessaire à sa propre validation statistique,
    sans jamais engager de capital réel sur une estimation non validée -
    `decision_engine/main.py` est responsable de ne jamais appeler cette
    fonction pour une décision en mode réel."""
    if classify_calibration_maturity(calibration) == COLLECTING:
        return None
    return apply_logistic_parameters(calibration, fused_score)
