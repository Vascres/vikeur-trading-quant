"""Point d'entrée du service data_collector (Phase 7 ; ADR-0012).

Respecte la frontière Phase 2 : ce module ne connaît QUE les
ExchangeAdapter (via la fabrique, ADR-0012) et Redis (transport). Il
n'importe jamais data_normalizer, feature_engine, decision_engine, etc.
(contrat import-linter, Phase 5/2).

Boucle sur `ACTIVE_EXCHANGES` (ADR-0012) - jamais un seul exchange en
dur. Les symboles suivis restent une liste unique de symboles NATIFS par
exchange (Phase 1 §6) ; un même symbole canonique peut avoir un format
natif différent d'un exchange à l'autre (cf. `shared/symbol_mapping.py`).
"""

import asyncio
import json
import logging
import os

import redis.asyncio as redis

from data_collector.adapters.factory import build_exchange_adapter
from shared.exchange_adapter import ExchangeAdapter
from shared.exchange_config import ACTIVE_EXCHANGES

logger = logging.getLogger(__name__)

# Paires suivies en V1 (5-15 paires liquides, Phase 1 §6) - configurable
# par exchange (ADR-0012) : TRACKED_SYMBOLS_HTX, TRACKED_SYMBOLS_BINANCE...
# ; retombe sur TRACKED_SYMBOLS (nom générique) si la variable spécifique
# à l'exchange n'est pas définie, pour rester compatible avec un
# déploiement mono-exchange existant.
DEFAULT_SYMBOLS = "btcusdt,ethusdt,solusdt"


def _tracked_symbols(exchange: str) -> list[str]:
    specific = os.environ.get(f"TRACKED_SYMBOLS_{exchange.upper()}")
    if specific is not None:
        return specific.split(",")
    return os.environ.get("TRACKED_SYMBOLS", DEFAULT_SYMBOLS).split(",")


REDIS_URL = os.environ["REDIS_URL"]
JOURNAL_CHANNEL = "events:journal"


async def main() -> None:
    redis_client = redis.from_url(REDIS_URL)

    def publish_journal_event(event_type: str, payload: dict) -> None:
        asyncio.create_task(
            redis_client.publish(
                JOURNAL_CHANNEL,
                json.dumps({"source_module": "data_collector", "event_type": event_type, "payload": payload}),
            )
        )

    adapters = [
        build_exchange_adapter(exchange, journal_publisher=publish_journal_event)
        for exchange in ACTIVE_EXCHANGES
    ]

    tasks = []
    for adapter in adapters:
        symbols = _tracked_symbols(adapter.exchange_name)
        tasks.append(asyncio.create_task(_forward_trades(adapter, symbols, redis_client)))
        tasks.append(asyncio.create_task(_forward_order_book(adapter, symbols, redis_client)))

    try:
        await asyncio.gather(*tasks)
    finally:
        for adapter in adapters:
            await adapter.close()
        await redis_client.aclose()


async def _forward_trades(adapter: ExchangeAdapter, symbols: list[str], redis_client: redis.Redis) -> None:
    async for message in adapter.stream_trades(symbols):
        await redis_client.publish(
            f"raw:{adapter.exchange_name}:trade",
            json.dumps({"native_symbol": message.native_symbol, "payload": message.payload}),
        )


async def _forward_order_book(
    adapter: ExchangeAdapter, symbols: list[str], redis_client: redis.Redis
) -> None:
    async for message in adapter.stream_order_book(symbols):
        await redis_client.publish(
            f"raw:{adapter.exchange_name}:depth",
            json.dumps({"native_symbol": message.native_symbol, "payload": message.payload}),
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
