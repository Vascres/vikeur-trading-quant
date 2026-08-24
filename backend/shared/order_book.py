"""Marche de carnet d'ordres (ADR-0021) - généralise la logique déjà
écrite et testée dans `risk_engine/rules/liquidity_slippage_fees.py`
(Phase 13), pour que le simulateur d'exécution de paires (ADR-0021)
puisse l'utiliser sans dupliquer le calcul. Fonction pure, aucune
dépendance de couche - peut être importée par `shared`, `risk_engine`,
et les futurs modules de stratégie sans violer les contrats
import-linter existants.
"""

from __future__ import annotations

from decimal import Decimal


def walk_order_book(
    levels: list[tuple[Decimal, Decimal]], target_quantity: Decimal
) -> tuple[Decimal, Decimal]:
    """Simule le remplissage niveau par niveau d'un carnet d'ordres.

    Retourne `(prix_moyen_pondere, quantite_totale_remplie)`. Si le
    carnet ne peut pas absorber `target_quantity` en totalité,
    `quantite_totale_remplie < target_quantity` - jamais une exception,
    à l'appelant de décider ce que ça signifie (liquidité insuffisante,
    remplissage partiel probable, etc.)."""
    remaining = target_quantity
    total_cost = Decimal(0)
    total_filled = Decimal(0)

    for price, quantity in levels:
        take = min(remaining, quantity)
        total_cost += take * price
        total_filled += take
        remaining -= take
        if remaining <= 0:
            break

    if total_filled == 0:
        return Decimal(0), Decimal(0)

    return total_cost / total_filled, total_filled
