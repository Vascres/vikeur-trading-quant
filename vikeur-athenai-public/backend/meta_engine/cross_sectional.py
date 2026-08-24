"""Classement cross-sectionnel par momentum relatif (ADR-0017).

Calculé une seule fois par cycle, avant la boucle d'évaluation par
symbole (`decision_engine/main.py`) - contrairement aux grandeurs déjà
présentes dans ce module (`cost_estimation.py`), qui ne dépendent que
d'un seul symbole à la fois, un classement cross-sectionnel a par nature
besoin de voir tous les symboles suivis au même instant.

Limite assumée et documentée (ADR-0017 §6) : avec seulement 3 symboles
suivis aujourd'hui (BTC/USDT, ETH/USDT, SOL/USDT), un vrai classement
par déciles (pratique classique en finance quant) n'a pas de sens
statistique - ceci implémente une version minimale à 3 positions
(leader / retardataire / milieu), suffisante pour prouver le mécanisme
et le contrat d'intégration, pas la version définitive. Robustesse
statistique croissante attendue à mesure que l'univers suivi s'élargit
(roadmap, breadth).

Simplification assumée sur les égalités exactes : en cas d'ex-aequo
strict entre plusieurs symboles au maximum ou au minimum, seul le
premier rencontré (ordre d'itération du dict fourni) est retenu comme
leader/retardataire - rare en pratique avec des nombres réels continus,
non traité comme un cas spécial pour garder la fonction simple.
"""

from __future__ import annotations

LEADER_RANK = 1.0
LAGGARD_RANK = -1.0
MIDDLE_RANK = 0.0


def classify_cross_sectional_ranks(momentum_by_symbol: dict[str, float]) -> dict[str, dict[str, float]]:
    """Retourne, pour chaque symbole fourni :
    - `cross_sectional_rank` : `LEADER_RANK` (momentum le plus élevé du
      cycle), `LAGGARD_RANK` (le plus faible), ou `MIDDLE_RANK` sinon.
    - `cross_sectional_spread` : écart leader - retardataire (même valeur
      pour tous les symboles d'un même cycle) - une mesure de dispersion
      réelle entre symboles, jamais 0 par défaut (0 signifie une vraie
      absence de dispersion, pas une donnée manquante).

    Univers insuffisant (< 2 symboles avec une valeur de momentum
    disponible) : tous les symboles reçoivent `MIDDLE_RANK`/spread nul -
    aucun classement n'a de sens à cette échelle, jamais une opinion
    fabriquée sur un univers vide ou singleton (principe directeur 2).
    """
    if len(momentum_by_symbol) < 2:
        return {
            symbol: {"cross_sectional_rank": MIDDLE_RANK, "cross_sectional_spread": 0.0}
            for symbol in momentum_by_symbol
        }

    leader_symbol = max(momentum_by_symbol, key=momentum_by_symbol.get)
    laggard_symbol = min(momentum_by_symbol, key=momentum_by_symbol.get)
    spread = momentum_by_symbol[leader_symbol] - momentum_by_symbol[laggard_symbol]

    ranks: dict[str, dict[str, float]] = {}
    for symbol in momentum_by_symbol:
        if symbol == leader_symbol and symbol != laggard_symbol:
            rank = LEADER_RANK
        elif symbol == laggard_symbol and symbol != leader_symbol:
            rank = LAGGARD_RANK
        else:
            rank = MIDDLE_RANK
        ranks[symbol] = {"cross_sectional_rank": rank, "cross_sectional_spread": spread}
    return ranks
