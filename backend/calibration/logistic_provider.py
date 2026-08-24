"""Calibration par régression logistique / Platt scaling (ADR-0009).

Choisie plutôt qu'une régression isotonique ou un binning empirique
précisément parce que le volume de trades clôturés est aujourd'hui très
faible (cf. ADR-0009) : seulement 2 paramètres à estimer, donc une
variance bien plus faible qu'une méthode non paramétrique avec peu de
données.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss

from shared.calibration_provider import CalibrationProvider, CalibrationRun, apply_logistic_parameters

# Sous ce seuil, aucune tentative d'ajustement n'est faite - la
# calibration est directement marquée non validée (ADR-0009).
DEFAULT_MINIMUM_SAMPLE_SIZE = 30

# Même convention que ml_engine/training_pipeline.py - chronologique,
# jamais aléatoire (pas de fuite du futur).
TRAIN_VALIDATION_SPLIT = 0.8


class LogisticCalibrationProvider(CalibrationProvider):
    method_name = "platt_scaling"

    def __init__(self, minimum_sample_size: int = DEFAULT_MINIMUM_SAMPLE_SIZE) -> None:
        self._minimum_sample_size = minimum_sample_size

    async def calibrate(
        self, historical_scores: list[float], historical_outcomes: list[bool]
    ) -> CalibrationRun:
        n = len(historical_scores)
        now = datetime.now(tz=UTC)

        if n < self._minimum_sample_size:
            return CalibrationRun(
                method=self.method_name,
                computed_at=now,
                sample_size=n,
                is_validated=False,
                reason=f"Échantillon insuffisant : {n} trade(s) clôturé(s), {self._minimum_sample_size} requis.",
            )

        split_index = int(n * TRAIN_VALIDATION_SPLIT)
        train_scores, val_scores = historical_scores[:split_index], historical_scores[split_index:]
        train_outcomes, val_outcomes = historical_outcomes[:split_index], historical_outcomes[split_index:]

        if len(set(train_outcomes)) < 2:
            return CalibrationRun(
                method=self.method_name,
                computed_at=now,
                sample_size=n,
                is_validated=False,
                reason="L'échantillon d'entraînement ne contient qu'un seul type d'issue (gagnant ou perdant) - impossible d'ajuster une régression logistique.",
            )

        model = LogisticRegression()
        X_train = np.array(train_scores).reshape(-1, 1)
        model.fit(X_train, train_outcomes)

        if val_scores:
            X_val = np.array(val_scores).reshape(-1, 1)
            predicted_probabilities = model.predict_proba(X_val)[:, 1]
            brier = float(brier_score_loss(val_outcomes, predicted_probabilities))
        else:
            # Échantillon trop juste pour laisser 20% en validation -
            # ne devrait pas arriver au-delà du seuil minimal par défaut,
            # mais un seuil personnalisé plus bas pourrait l'atteindre.
            brier = None

        # Un Brier score > 0.25 équivaut à ne pas faire mieux qu'une
        # estimation constante à 0.5 sur un problème équilibré - seuil de
        # validation minimal, documenté et configurable par ADR futur si
        # l'expérience opérationnelle le justifie (ADR-0009, §Conséquences).
        is_validated = brier is not None and brier <= 0.25

        return CalibrationRun(
            method=self.method_name,
            computed_at=now,
            sample_size=n,
            is_validated=is_validated,
            brier_score=brier,
            parameters={
                "intercept": float(model.intercept_[0]),
                "coefficient": float(model.coef_[0][0]),
            },
            reason=None if is_validated else f"Brier score de validation trop élevé : {brier}.",
        )

    def apply(self, calibration: CalibrationRun, raw_score: float) -> float:
        return apply_logistic_parameters(calibration, raw_score)
