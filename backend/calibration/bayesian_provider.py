"""Calibration bayésienne par régression logistique régularisée (MAP) -
ADR-0015.

Équivalence classique (Bishop, *Pattern Recognition and Machine
Learning*, §4.5) : une régression logistique avec pénalité L2 de force
`C` est l'estimateur du maximum a posteriori (MAP) sous un prior gaussien
`N(0, 1/C)` sur les coefficients. Aucune nouvelle dépendance requise :
`scikit-learn` (déjà utilisé par `calibration.logistic_provider` et
`ml_engine`) suffit - conforme à Development Standards §5.

Contrairement à `LogisticCalibrationProvider` (ADR-0009, seuil dur à 30
échantillons - en dessous, refus pur), cette implémentation produit
toujours une estimation dès le premier trade clôturé, avec un degré de
régularisation qui décroît à mesure que l'échantillon grandit :
- en dessous de `minimum_sample_size_preliminary`, aucune tentative
  n'est faite (même le prior seul n'a pas de sens à publier comme une
  "calibration" - niveau `collecting` du Confidence Lifecycle,
  `shared/confidence_lifecycle.py`) ;
- entre les deux seuils, une estimation existe mais reste fortement
  tirée vers le prior non informatif (probabilité de succès = 50% en
  l'absence de signal, `PRIOR_INTERCEPT`/`PRIOR_COEFFICIENT` nuls -
  jamais un edge fabriqué, principe directeur 2) - niveau `preliminary` ;
- au-delà de `minimum_sample_size_validated`, la régularisation devient
  légère (proche du maximum de vraisemblance non régularisé, donc du
  comportement de `LogisticCalibrationProvider`) et la même barre de
  validation qu'ADR-0009 s'applique (Brier score de validation <= 0.25)
  avant de passer au niveau `validated`.

Cf. ADR-0015 pour la comparaison complète face à l'alternative (seuil
dur hérité d'ADR-0009, jamais silencieusement remplacée - Development
Standards, esprit d'ADR-0009 §Évolutions futures).
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss

from shared.calibration_provider import CalibrationProvider, CalibrationRun, apply_logistic_parameters

# Seuils du Confidence Lifecycle (ADR-0015) - dupliqués ici en valeurs
# par défaut du constructeur pour rester injectables en test, mais
# identiques par défaut à `shared/confidence_lifecycle.py`.
MINIMUM_SAMPLE_SIZE_PRELIMINARY = 5
MINIMUM_SAMPLE_SIZE_VALIDATED = 30

TRAIN_VALIDATION_SPLIT = 0.8  # même convention chronologique que logistic_provider/ml_engine

# Prior faiblement informatif : probabilité de succès = 50% en l'absence
# de toute donnée (intercept nul, coefficient nul) - jamais un edge
# fabriqué (principe directeur 2).
PRIOR_INTERCEPT = 0.0
PRIOR_COEFFICIENT = 0.0

# Force de régularisation (le `C` de scikit-learn, inverse de la
# variance du prior gaussien) aux deux bornes de la plage d'échantillon
# considérée - schéma d'interpolation linéaire, documenté et testé, à
# ajuster par un futur ADR si l'expérience opérationnelle le justifie
# (même esprit qu'ADR-0009 §Évolutions futures - jamais un remplacement
# silencieux).
_C_AT_MIN_SAMPLE = 0.05  # très fortement régularisé au seuil "preliminary"
_C_AT_VALIDATED_SAMPLE = 1.0  # régularisation légère au seuil "validated" - jamais nulle


def _regularization_strength(sample_size: int) -> float:
    """Interpole `C` entre les deux bornes, plafonné au-delà du seuil de
    validation - une régularisation légère mais jamais totalement nulle,
    cohérent avec une approche bayésienne (le prior ne disparaît jamais
    complètement, il s'estompe à mesure que les données s'accumulent)."""
    if sample_size <= MINIMUM_SAMPLE_SIZE_PRELIMINARY:
        return _C_AT_MIN_SAMPLE
    if sample_size >= MINIMUM_SAMPLE_SIZE_VALIDATED:
        return _C_AT_VALIDATED_SAMPLE
    progress = (sample_size - MINIMUM_SAMPLE_SIZE_PRELIMINARY) / (
        MINIMUM_SAMPLE_SIZE_VALIDATED - MINIMUM_SAMPLE_SIZE_PRELIMINARY
    )
    return _C_AT_MIN_SAMPLE + progress * (_C_AT_VALIDATED_SAMPLE - _C_AT_MIN_SAMPLE)


class BayesianCalibrationProvider(CalibrationProvider):
    method_name = "bayesian_logistic_map"

    def __init__(
        self,
        minimum_sample_size_preliminary: int = MINIMUM_SAMPLE_SIZE_PRELIMINARY,
        minimum_sample_size_validated: int = MINIMUM_SAMPLE_SIZE_VALIDATED,
    ) -> None:
        self._min_preliminary = minimum_sample_size_preliminary
        self._min_validated = minimum_sample_size_validated

    async def calibrate(
        self, historical_scores: list[float], historical_outcomes: list[bool]
    ) -> CalibrationRun:
        n = len(historical_scores)
        now = datetime.now(tz=UTC)

        if n < self._min_preliminary:
            return CalibrationRun(
                method=self.method_name,
                computed_at=now,
                sample_size=n,
                is_validated=False,
                parameters={"intercept": PRIOR_INTERCEPT, "coefficient": PRIOR_COEFFICIENT},
                reason=(
                    f"Échantillon insuffisant même pour une estimation préliminaire : "
                    f"{n} trade(s) clôturé(s), {self._min_preliminary} requis pour le niveau "
                    f"'preliminary' du Confidence Lifecycle (ADR-0015)."
                ),
            )

        split_index = int(n * TRAIN_VALIDATION_SPLIT)
        train_scores, val_scores = historical_scores[:split_index], historical_scores[split_index:]
        train_outcomes, val_outcomes = historical_outcomes[:split_index], historical_outcomes[split_index:]

        c = _regularization_strength(n)

        if len(set(train_outcomes)) < 2:
            # Échantillon d'entraînement dégénéré (un seul type d'issue) -
            # contrairement à ADR-0009 (refus pur dans ce cas), l'approche
            # bayésienne retombe proprement sur le prior seul plutôt que
            # d'échouer : c'est un résultat légitime (fortement incertain,
            # marqué comme tel via `reason`), pas une erreur.
            parameters = {"intercept": PRIOR_INTERCEPT, "coefficient": PRIOR_COEFFICIENT}
            brier = None
        else:
            model = LogisticRegression(C=c)
            X_train = np.array(train_scores).reshape(-1, 1)
            model.fit(X_train, train_outcomes)
            parameters = {
                "intercept": float(model.intercept_[0]),
                "coefficient": float(model.coef_[0][0]),
            }
            if val_scores:
                X_val = np.array(val_scores).reshape(-1, 1)
                predicted_probabilities = model.predict_proba(X_val)[:, 1]
                brier = float(brier_score_loss(val_outcomes, predicted_probabilities))
            else:
                brier = None

        is_validated = n >= self._min_validated and brier is not None and brier <= 0.25

        if is_validated:
            reason = None
        elif n < self._min_validated:
            reason = (
                f"Niveau 'preliminary' (Confidence Lifecycle, ADR-0015) : {n} trade(s) "
                f"clôturé(s) sur {self._min_validated} requis pour 'validated' - probabilité "
                f"disponible mais fortement régularisée vers le prior (régularisation C={c:.3f}). "
                f"Utilisable en mode paper uniquement (ADR-0014)."
            )
        else:
            reason = f"Brier score de validation trop élevé : {brier}."

        return CalibrationRun(
            method=self.method_name,
            computed_at=now,
            sample_size=n,
            is_validated=is_validated,
            brier_score=brier,
            parameters=parameters,
            reason=reason,
        )

    def apply(self, calibration: CalibrationRun, raw_score: float) -> float:
        """Contrairement à `LogisticCalibrationProvider.apply()` (ADR-0009),
        peut légitimement être appelée sur une calibration dont
        `is_validated` est `False`, dès lors que `sample_size >=
        minimum_sample_size_preliminary` - c'est la responsabilité de
        l'appelant (`meta_engine.calibration_lookup`, `decision_engine`)
        de vérifier le niveau du Confidence Lifecycle avant d'appeler
        `apply()`, et de n'exposer un résultat "preliminary" qu'en mode
        paper (ADR-0014, ADR-0015)."""
        return apply_logistic_parameters(calibration, raw_score)
