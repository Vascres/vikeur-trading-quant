"""Fabrique d'adaptateurs d'exchange (ADR-0012).

Ajouter un troisième exchange demain consiste à écrire son adaptateur
puis à l'enregistrer ici - jamais à modifier `data_collector/main.py`
ou tout service en aval.
"""

from __future__ import annotations

from data_collector.adapters.binance import BinanceAdapter
from data_collector.adapters.htx import HTXAdapter
from shared.exchange_adapter import ExchangeAdapter
from shared.exchange_config import get_exchange_credentials

_ADAPTER_CLASSES: dict[str, type[ExchangeAdapter]] = {
    "htx": HTXAdapter,
    "binance": BinanceAdapter,
}


class UnknownExchangeError(ValueError):
    """Levée quand un nom d'exchange ne figure pas dans la fabrique."""


def build_exchange_adapter(exchange: str, journal_publisher=None) -> ExchangeAdapter:
    try:
        adapter_class = _ADAPTER_CLASSES[exchange]
    except KeyError as exc:
        raise UnknownExchangeError(
            f"Exchange inconnu de la fabrique : '{exchange}'. Enregistré : {list(_ADAPTER_CLASSES)}."
        ) from exc

    api_key, api_secret = get_exchange_credentials(exchange)
    return adapter_class(journal_publisher=journal_publisher, api_key=api_key, api_secret=api_secret)
