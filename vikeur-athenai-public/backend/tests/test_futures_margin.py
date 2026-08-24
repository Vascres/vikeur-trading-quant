"""Tests de shared.futures_margin (Étapes 7-8 du plan validé le 16/08/2026)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from shared.futures_adapter import PositionSide
from shared.futures_margin import (
    compute_liquidation_price,
    compute_max_loss_stop_price,
    compute_required_margin,
)


def test_compute_required_margin_divides_notional_by_leverage():
    assert compute_required_margin(Decimal("150"), leverage=2) == Decimal("75")


def test_compute_required_margin_at_1x_equals_notional():
    assert compute_required_margin(Decimal("150"), leverage=1) == Decimal("150")


def test_compute_required_margin_rejects_non_positive_leverage():
    with pytest.raises(ValueError):
        compute_required_margin(Decimal("150"), leverage=0)


def test_compute_liquidation_price_matches_mandate_worked_example():
    """Cas exact vérifié dans l'audit du 16/08/2026 : ETH à 3000$, levier
    2x, marge de maintenance 0,4% -> liquidation vers 1512$."""
    liquidation = compute_liquidation_price(
        entry_price=Decimal("3000"),
        leverage=2,
        side=PositionSide.LONG,
        maintenance_margin_rate=Decimal("0.004"),
    )
    assert liquidation == Decimal("1512.000")


def test_compute_liquidation_price_short_is_above_entry():
    liquidation = compute_liquidation_price(
        entry_price=Decimal("3000"),
        leverage=2,
        side=PositionSide.SHORT,
        maintenance_margin_rate=Decimal("0.004"),
    )
    assert liquidation > Decimal("3000")
    assert liquidation == Decimal("4488.000")


def test_compute_liquidation_price_long_is_below_entry():
    liquidation = compute_liquidation_price(entry_price=Decimal("3000"), leverage=2, side=PositionSide.LONG)
    assert liquidation < Decimal("3000")


def test_compute_liquidation_price_higher_leverage_is_closer_to_entry():
    """Plus le levier est élevé, plus la liquidation survient tôt - la
    propriété la plus importante à vérifier pour ne jamais inverser un
    signe par erreur."""
    liquidation_2x = compute_liquidation_price(Decimal("3000"), leverage=2, side=PositionSide.LONG)
    liquidation_5x = compute_liquidation_price(Decimal("3000"), leverage=5, side=PositionSide.LONG)
    assert liquidation_5x > liquidation_2x  # 5x liquide à un prix plus haut (plus proche de l'entrée)


def test_compute_liquidation_price_rejects_non_positive_leverage():
    with pytest.raises(ValueError):
        compute_liquidation_price(Decimal("3000"), leverage=0, side=PositionSide.LONG)


def test_compute_max_loss_stop_price_matches_mandate_worked_example():
    """Cas exact du mandat : marge 75$, notionnel 150$ (levier 2x), perte
    maximale visée 3$ (4% de la marge) -> stop vers 2940$ pour une
    entrée à 3000$."""
    stop_price = compute_max_loss_stop_price(
        entry_price=Decimal("3000"),
        leverage=2,
        side=PositionSide.LONG,
        max_loss_fraction_of_margin=Decimal("0.04"),
    )
    assert stop_price == Decimal("2940.00")

    # Vérification indépendante : perte réelle au prix de stop.
    quantity = Decimal("150") / Decimal("3000")  # notionnel / prix d'entrée
    loss = (Decimal("3000") - stop_price) * quantity
    assert loss == Decimal("3.0000")


def test_compute_max_loss_stop_price_stays_above_liquidation_for_reasonable_fraction():
    """Le stop doit toujours se déclencher AVANT la liquidation pour un
    plafond de perte raisonnable - propriété de sécurité centrale du
    mandat §8 ("Le Risk Engine refuse d'être liquidé par l'exchange")."""
    entry = Decimal("3000")
    leverage = 2
    stop_price = compute_max_loss_stop_price(
        entry_price=entry,
        leverage=leverage,
        side=PositionSide.LONG,
        max_loss_fraction_of_margin=Decimal("0.04"),
    )
    liquidation_price = compute_liquidation_price(entry, leverage=leverage, side=PositionSide.LONG)
    assert stop_price > liquidation_price


def test_compute_max_loss_stop_price_short_is_above_entry():
    stop_price = compute_max_loss_stop_price(
        entry_price=Decimal("3000"),
        leverage=2,
        side=PositionSide.SHORT,
        max_loss_fraction_of_margin=Decimal("0.04"),
    )
    assert stop_price > Decimal("3000")


def test_compute_max_loss_stop_price_rejects_non_positive_leverage():
    with pytest.raises(ValueError):
        compute_max_loss_stop_price(
            Decimal("3000"), leverage=0, side=PositionSide.LONG, max_loss_fraction_of_margin=Decimal("0.04")
        )
