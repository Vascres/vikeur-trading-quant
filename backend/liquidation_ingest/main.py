"""Service liquidation_ingest (chantier de données pour l'agent
Liquidation Cascade, 16/08/2026 - mandat §28 : "moteur phare" si les
données le confirment - cette étape ne construit que la donnée, jamais
le signal ni la décision, même discipline que chaque autre chantier de
ce projet).

Se connecte directement au flux public Binance Futures
(`BinanceFuturesAdapter.stream_liquidations`) - contrairement au reste
de la collecte de marché (`data_collector`, spot uniquement à ce jour,
frontière stricte "jamais d'accès DB"), ce service persiste directement
en base : les liquidations ne suivent pas le même pipeline de
normalisation que les prix/volumes (pas d'agrégation en chandelles), un
second chemin de collecte dédié est plus honnête qu'un détournement de
la frontière existante de `data_collector`.

Isolé du flux de décision live (même principe que `cost_model`/
`strategy_lifecycle`/`journal`/`notifications`) - contrat import-linter
dédié, jamais un chemin détourné vers `decision_engine`/`risk_engine`/
`execution_engine`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import asyncpg
import redis.asyncio as redis

from data_collector.adapters.binance_futures import BinanceFuturesAdapter, parse_liquidation_message
from shared.heartbeat import run_heartbeat

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
JOURNAL_CHANNEL = "events:journal"

DEFAULT_SYMBOLS_NATIVE = "btcusdt,ethusdt,solusdt"


def _tracked_symbols_native() -> list[str]:
    """Même convention que `data_collector/main.py::_tracked_symbols` -
    dupliquée plutôt qu'importée (ce service ne dépend jamais de
    `data_collector`, même principe d'isolation que le reste de ce
    projet)."""
    return os.environ.get("TRACKED_SYMBOLS_BINANCE_FUTURES", DEFAULT_SYMBOLS_NATIVE).split(",")


async def persist_liquidation_event(db_pool: asyncpg.Pool, event) -> None:
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO liquidation_events (exchange, symbol, side, price, quantity, notional, order_status, event_time)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8);
            """,
            event.exchange,
            event.symbol,
            event.side,
            event.price,
            event.quantity,
            event.notional,
            event.order_status,
            event.event_time,
        )


async def consume_liquidations(
    adapter: BinanceFuturesAdapter, db_pool: asyncpg.Pool, symbols_native: list[str]
) -> None:
    async for raw_message in adapter.stream_liquidations(symbols_native):
        event = parse_liquidation_message(raw_message)
        if event is None:
            continue
        try:
            await persist_liquidation_event(db_pool, event)
        except Exception:
            # Ne jamais faire tomber le flux pour un seul événement -
            # même discipline que journal/main.py::consume_and_persist.
            logger.exception("Échec d'écriture d'un événement de liquidation - événement perdu : %r", event)


async def main() -> None:
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
    redis_client = redis.from_url(REDIS_URL)
    asyncio.create_task(run_heartbeat())

    def publish_journal_event(event_type: str, payload: dict) -> None:
        asyncio.create_task(
            redis_client.publish(
                JOURNAL_CHANNEL,
                json.dumps(
                    {"source_module": "liquidation_ingest", "event_type": event_type, "payload": payload},
                    default=str,
                ),
            )
        )

    adapter = BinanceFuturesAdapter(
        journal_publisher=publish_journal_event
    )  # flux public - aucune clé API requise
    symbols_native = _tracked_symbols_native()

    publish_journal_event("liquidation_ingest.started", {"symbols": symbols_native})

    try:
        await consume_liquidations(adapter, db_pool, symbols_native)
    finally:
        await adapter.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
