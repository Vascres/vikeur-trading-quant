"""Tests de risk_engine.main.determine_market_type (ADR-0019).

Fonction pure isolant toute la logique de routage spot/futures - le
cœur du branchement du futures dans le pipeline de décision.
"""

from __future__ import annotations

from decimal import Decimal

from risk_engine.main import determine_market_type
from shared.strategy import Side


def test_buy_always_routes_to_spot_when_no_position_exists():
    result = determine_market_type(
        Side.BUY, existing_spot_quantity=Decimal("0"), existing_futures_quantity=Decimal("0")
    )
    assert result == "spot"


def test_buy_stays_spot_even_with_futures_routing_enabled():
    result = determine_market_type(
        Side.BUY,
        existing_spot_quantity=Decimal("0"),
        existing_futures_quantity=Decimal("0"),
        futures_routing_enabled=True,
    )
    assert result == "spot"


def test_sell_without_position_stays_spot_when_flag_disabled():
    """Comportement inchangé tant que FUTURES_ROUTING_ENABLED n'est pas
    explicitement activé - rejeté ensuite par SpotNoShortingRule,
    exactement comme avant ADR-0018/0019."""
    result = determine_market_type(
        Side.SELL,
        existing_spot_quantity=Decimal("0"),
        existing_futures_quantity=Decimal("0"),
        futures_routing_enabled=False,
    )
    assert result == "spot"


def test_sell_without_position_routes_to_futures_when_flag_enabled():
    result = determine_market_type(
        Side.SELL,
        existing_spot_quantity=Decimal("0"),
        existing_futures_quantity=Decimal("0"),
        futures_routing_enabled=True,
    )
    assert result == "futures_perpetual"


def test_sell_with_existing_spot_position_stays_spot():
    """Clôture normale d'une position spot déjà détenue - inchangé."""
    result = determine_market_type(
        Side.SELL,
        existing_spot_quantity=Decimal("0.5"),
        existing_futures_quantity=Decimal("0"),
        futures_routing_enabled=True,
    )
    assert result == "spot"


def test_existing_futures_position_takes_priority_over_flag():
    """Une position futures déjà ouverte gouverne le routage, quel que
    soit le sens du nouveau signal (ADR-0019 §2) - jamais un nouveau
    calcul quand une position existe déjà."""
    result = determine_market_type(
        Side.BUY,
        existing_spot_quantity=Decimal("0"),
        existing_futures_quantity=Decimal("1.0"),
        futures_routing_enabled=False,
    )
    assert result == "futures_perpetual"


def test_existing_futures_position_takes_priority_over_spot_position():
    """Cas limite : les deux existent (ne devrait pas arriver en pratique
    avec la politique actuelle, mais la priorité doit rester déterministe)."""
    result = determine_market_type(
        Side.SELL,
        existing_spot_quantity=Decimal("0.3"),
        existing_futures_quantity=Decimal("1.0"),
    )
    assert result == "futures_perpetual"
