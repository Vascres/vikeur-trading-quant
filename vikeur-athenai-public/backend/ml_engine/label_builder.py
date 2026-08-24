"""Construction du label d'entraînement (Phase 16, §4).

Fonction pure : listes de prix en entrée, labels binaires en sortie -
testable sans base de données.
"""


def build_labels(closes: list[float], horizon_periods: int, threshold: float = 0.0) -> list[int | None]:
    """Pour chaque instant i, label = 1 si le rendement futur sur
    `horizon_periods` dépasse `threshold`, 0 sinon. None si l'horizon
    dépasse les données disponibles (pas de label calculable - à exclure
    du jeu d'entraînement par l'appelant, jamais à deviner).
    """
    labels: list[int | None] = []
    for i in range(len(closes)):
        future_index = i + horizon_periods
        if future_index >= len(closes) or closes[i] <= 0:
            labels.append(None)
            continue
        forward_return = (closes[future_index] - closes[i]) / closes[i]
        labels.append(1 if forward_return > threshold else 0)
    return labels


def align_features_and_labels(
    feature_rows: list[list[float]], labels: list[int | None]
) -> tuple[list[list[float]], list[int]]:
    """Filtre les lignes dont le label est None (Phase 16, §4)."""
    aligned_X = []
    aligned_y = []
    for row, label in zip(feature_rows, labels):
        if label is not None:
            aligned_X.append(row)
            aligned_y.append(label)
    return aligned_X, aligned_y
