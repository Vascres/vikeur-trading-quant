"""Calcul des fractions d'allocation de capital (Phase 17, §4).

Fonction pure. Résultat purement informatif - jamais appliqué
automatiquement (Phase 17, §3).
"""


def compute_allocation_fractions(scores: dict[str, float]) -> dict[str, float]:
    """Alloue proportionnellement aux scores positifs, normalisé à 1.

    Les stratégies à score négatif ou nul reçoivent une fraction de 0
    (pas d'allocation négative - une stratégie non prometteuse reçoit
    simplement rien, elle ne "doit" pas de capital aux autres).
    """
    positive_scores = {name: max(score, 0.0) for name, score in scores.items()}
    total = sum(positive_scores.values())

    if total <= 0:
        return dict.fromkeys(scores, 0.0)

    return {name: score / total for name, score in positive_scores.items()}
