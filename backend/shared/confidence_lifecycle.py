"""Confidence Lifecycle (ADR-0015) - vocabulaire de maturité générique.

Premier composant instancié : la calibration probabiliste
(`calibration_runs`). L'étude d'architecture "Confidence Lifecycle"
(document de réflexion, pas un ADR) envisageait une généralisation
complète (registre générique multi-composants, séparation stricte
learning/trading) - délibérément différée jusqu'à un second cas d'usage
réel (probablement `ml_engine`), pour éviter une sur-généralisation
construite sur un seul cas d'usage. Seul le vocabulaire à 3 niveaux
utile au deadlock actuel est adopté ici, dès maintenant, pour ne pas
avoir à migrer un nom plus tard (cf. ADR-0015 §Conséquences).
"""

from __future__ import annotations

from shared.calibration_provider import CalibrationRun

COLLECTING = "collecting"
PRELIMINARY = "preliminary"
VALIDATED = "validated"

# Sous ce seuil, aucune estimation n'est jugée exploitable, quel que
# soit le mode d'exécution (ADR-0015).
MIN_SAMPLE_PRELIMINARY = 5

# Seuil hérité tel quel d'ADR-0009 - la barre de validation statistique
# complète n'a jamais été remise en cause par ce chantier.
MIN_SAMPLE_VALIDATED = 30


def classify_calibration_maturity(calibration: CalibrationRun | None) -> str:
    """Classe une `CalibrationRun` selon le Confidence Lifecycle.

    - `validated` : `is_validated=True` (barre statistique ADR-0009/0015
      franchie - échantillon >= 30 et Brier score de validation <= 0.25).
      Seul niveau autorisé à peser sur du capital réel (mode `real`).
    - `preliminary` : pas encore validée, mais échantillon >= 5 - une
      probabilité existe (fortement régularisée vers le prior), jamais
      utilisable en mode `real`, utilisable en mode `paper` (ADR-0014).
    - `collecting` : aucune calibration exploitable (aucune ligne
      persistée, ou échantillon < 5) - aucune probabilité disponible,
      quel que soit le mode d'exécution. En mode `paper` uniquement, le
      pipeline de décision peut se rabattre sur le score brut fusionné
      (ADR-0014, `decision_engine.thresholds.evaluate_bootstrap_verdict`).
    """
    if calibration is None:
        return COLLECTING
    if calibration.is_validated:
        return VALIDATED
    if calibration.sample_size >= MIN_SAMPLE_PRELIMINARY:
        return PRELIMINARY
    return COLLECTING
