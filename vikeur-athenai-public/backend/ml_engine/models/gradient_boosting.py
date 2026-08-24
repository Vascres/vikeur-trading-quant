import pickle

from sklearn.ensemble import GradientBoostingClassifier

from shared.ml_model import MLModel, MLModelMetadata


class GradientBoostingModel(MLModel):
    metadata = MLModelMetadata(name="gradient_boosting", algorithm="GradientBoostingClassifier")

    def __init__(self, random_state: int = 42) -> None:
        self._model = GradientBoostingClassifier(random_state=random_state)

    def fit(self, X: list[list[float]], y: list[int]) -> None:
        self._model.fit(X, y)

    def predict_proba(self, X: list[list[float]]) -> list[float]:
        return [proba[1] for proba in self._model.predict_proba(X)]

    def serialize(self) -> bytes:
        return pickle.dumps(self._model)

    @classmethod
    def deserialize(cls, data: bytes) -> "GradientBoostingModel":
        instance = cls()
        instance._model = pickle.loads(data)
        return instance
