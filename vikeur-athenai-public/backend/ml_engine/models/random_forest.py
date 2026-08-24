import pickle

from sklearn.ensemble import RandomForestClassifier

from shared.ml_model import MLModel, MLModelMetadata


class RandomForestModel(MLModel):
    metadata = MLModelMetadata(name="random_forest", algorithm="RandomForestClassifier")

    def __init__(self, random_state: int = 42) -> None:
        self._model = RandomForestClassifier(random_state=random_state, n_estimators=200)

    def fit(self, X: list[list[float]], y: list[int]) -> None:
        self._model.fit(X, y)

    def predict_proba(self, X: list[list[float]]) -> list[float]:
        return [proba[1] for proba in self._model.predict_proba(X)]

    def serialize(self) -> bytes:
        return pickle.dumps(self._model)

    @classmethod
    def deserialize(cls, data: bytes) -> "RandomForestModel":
        instance = cls()
        instance._model = pickle.loads(data)
        return instance
