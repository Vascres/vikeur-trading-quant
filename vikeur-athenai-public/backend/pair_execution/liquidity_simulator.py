"""Simulateur d'exécution - probabilité de remplissage d'une jambe
(ADR-0021 §4.2).

Heuristique documentée, PAS un modèle statistique appris : aucun
historique réel de résultats de paires n'existe encore (même principe
que la calibration bayésienne à ses débuts, ADR-0015 - commencer par une
estimation honnête et documentée, jamais un chiffre inventé, laisser le
modèle s'affiner une fois de vraies données accumulées).

Fonction pure - aucune dépendance de couche, réutilisable par
`pair_execution` sans violer les contrats import-linter.
"""

from __future__ import annotations

from decimal import Decimal

from shared.order_book import walk_order_book

# Seuils de la fonction en paliers (ADR-0021 §4.2) - valeurs de départ
# prudentes, comme chaque autre seuil de ce projet, jamais présentées
# comme définitives. `depth_ratio` = profondeur visible cumulée sur les
# niveaux fournis / quantité demandée.
_DEPTH_RATIO_VERY_HIGH = Decimal("3.0")
_DEPTH_RATIO_HIGH = Decimal("1.5")
_DEPTH_RATIO_ADEQUATE = Decimal("1.0")
_DEPTH_RATIO_LOW = Decimal("0.5")

_PROBABILITY_VERY_HIGH = 0.99
_PROBABILITY_HIGH = 0.95
_PROBABILITY_ADEQUATE = 0.85
_PROBABILITY_LOW = 0.50
_PROBABILITY_VERY_LOW = 0.15


def estimate_fill_probability(levels: list[tuple[Decimal, Decimal]], target_quantity: Decimal) -> float:
    """Probabilité qu'un ordre FOK de taille `target_quantity` se remplisse
    intégralement, estimée à partir de la profondeur visible du carnet
    (`levels`, du meilleur prix vers le pire). Toujours dans `[0, 1]`.

    `target_quantity <= 0` retourne 0.0 - aucune quantité à remplir n'a
    pas de sens comme "probabilité de remplissage"."""
    if target_quantity <= 0:
        return 0.0

    _, filled = walk_order_book(levels, target_quantity)
    if filled <= 0:
        return 0.0

    total_depth = sum((quantity for _, quantity in levels), Decimal(0))
    if total_depth <= 0:
        return 0.0

    depth_ratio = total_depth / target_quantity

    if depth_ratio >= _DEPTH_RATIO_VERY_HIGH:
        return _PROBABILITY_VERY_HIGH
    if depth_ratio >= _DEPTH_RATIO_HIGH:
        return _PROBABILITY_HIGH
    if depth_ratio >= _DEPTH_RATIO_ADEQUATE:
        return _PROBABILITY_ADEQUATE
    if depth_ratio >= _DEPTH_RATIO_LOW:
        return _PROBABILITY_LOW
    return _PROBABILITY_VERY_LOW
