import random

import pytest

from ml_engine.models.gradient_boosting import GradientBoostingModel
from ml_engine.models.random_forest import RandomForestModel


def _synthetic_dataset(n: int = 200):
    random.seed(42)
    X = [[random.uniform(-1, 1), random.uniform(-1, 1)] for _ in range(n)]
    # Label fortement corrélé à la première feature - le modèle doit apprendre ce signal
    y = [1 if row[0] > 0 else 0 for row in X]
    return X, y


@pytest.mark.parametrize("model_class", [GradientBoostingModel, RandomForestModel])
def test_model_learns_simple_signal(model_class):
    X, y = _synthetic_dataset()
    model = model_class()
    model.fit(X, y)

    predictions = model.predict_proba([[0.9, 0.0], [-0.9, 0.0]])
    assert predictions[0] > 0.5  # feature positive -> forte probabilité de classe 1
    assert predictions[1] < 0.5  # feature négative -> faible probabilité


@pytest.mark.parametrize("model_class", [GradientBoostingModel, RandomForestModel])
def test_model_serialize_and_deserialize_roundtrip(model_class):
    X, y = _synthetic_dataset()
    model = model_class()
    model.fit(X, y)

    serialized = model.serialize()
    restored = model_class.deserialize(serialized)

    original_predictions = model.predict_proba(X[:5])
    restored_predictions = restored.predict_proba(X[:5])
    assert original_predictions == pytest.approx(restored_predictions)
