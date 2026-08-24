"""Fabrique d'adaptateurs futures (ADR-0018/0019) - parallèle et
indépendante de `data_collector/adapters/factory.py` (spot). Ajouter un
futures pour un autre exchange demain consiste à écrire son adaptateur
puis à l'enregistrer ici, jamais à modifier `execution_engine`."""

from __future__ import annotations

from data_collector.adapters.binance_futures import BinanceFuturesAdapter
from data_collector.adapters.htx_futures import HTXFuturesAdapter
from shared.exchange_config import get_futures_exchange_credentials
from shared.futures_adapter import FuturesExchangeAdapter

_FUTURES_ADAPTER_CLASSES: dict[str, type[FuturesExchangeAdapter]] = {
    "htx": HTXFuturesAdapter,
    "binance": BinanceFuturesAdapter,
}


class UnknownFuturesExchangeError(ValueError):
    """Levée quand un nom d'exchange ne figure pas dans la fabrique futures."""


def build_futures_exchange_adapter(exchange: str) -> FuturesExchangeAdapter:
    try:
        adapter_class = _FUTURES_ADAPTER_CLASSES[exchange]
    except KeyError as exc:
        raise UnknownFuturesExchangeError(
            f"Exchange futures inconnu de la fabrique : '{exchange}'. "
            f"Enregistré : {list(_FUTURES_ADAPTER_CLASSES)}."
        ) from exc

    api_key, api_secret = get_futures_exchange_credentials(exchange)
    return adapter_class(api_key=api_key, api_secret=api_secret)
