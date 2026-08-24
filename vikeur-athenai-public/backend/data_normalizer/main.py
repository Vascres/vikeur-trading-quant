"""Service data_normalizer (Phase 8).

Consomme les canaux Redis publiés par le collecteur (Phase 7) - aucun
import Python vers data_collector, uniquement un couplage par message
(cohérent avec le choix Redis Pub/Sub de la Phase 2).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import deque
from datetime import UTC, datetime
from decimal import Decimal

import asyncpg
import redis.asyncio as redis

from shared.exchange_config import ACTIVE_EXCHANGES
from shared.symbol_mapping import UnknownSymbolError, to_canonical

logger = logging.getLogger(__name__)

REDIS_URL = os.environ["REDIS_URL"]
DATABASE_URL = os.environ["DATABASE_URL"]
JOURNAL_CHANNEL = "events:journal"

GAP_THRESHOLD_SECONDS = int(os.environ.get("GAP_THRESHOLD_SECONDS", "60"))
DEDUP_CACHE_SIZE = 2000
BATCH_INTERVAL_SECONDS = 0.5
BATCH_MAX_SIZE = 500


class TradeNormalizer:
    """Encapsule le mapping, la détection de trous et la dé-duplication (Phase 8, §3)."""

    def __init__(self, exchange: str, publish_journal_event) -> None:
        self._exchange = exchange
        self._publish_journal_event = publish_journal_event
        self._last_trade_time: dict[str, datetime] = {}
        self._recent_trade_ids: dict[str, deque] = {}

    def normalize_trade_message(self, raw: dict) -> list[dict]:
        """Convertit un message de trade brut en lignes prêtes pour
        raw_market_data - format spécifique à l'exchange, jamais un seul
        format supposé universel.

        Bug réel trouvé le 18/08/2026 (en diagnostiquant pourquoi
        Binance, actif dans ACTIVE_EXCHANGES depuis des heures, n'avait
        jamais produit une seule ligne dans raw_market_data) : cette
        fonction ne savait parser QUE le format HTX (`payload.tick.
        data[]`) - un message Binance, dont la structure est totalement
        différente, produisait silencieusement une liste vide à chaque
        fois (`tick` absent -> `{}`, `.get("data", [])` -> `[]`),
        jamais une exception, jamais un événement journalisé. Chaque
        `TradeNormalizer` est bien instancié un par exchange actif
        (ADR-0012), mais le contenu de cette méthode ne l'était pas
        avant ce correctif.

        Formats vérifiés indépendamment contre leurs documentations
        respectives - jamais l'un déduit de l'autre :
        - HTX (`market.<symbol>.trade.detail`) : un message peut porter
          PLUSIEURS trades agrégés dans `tick.data[]`.
        - Binance (`<symbol>@trade`, PAS `@aggTrade` dont le format
          diffère) : un message = un seul trade, à la racine du payload."""
        native_symbol = raw["native_symbol"]
        try:
            canonical_symbol = to_canonical(self._exchange, native_symbol)
        except UnknownSymbolError as exc:
            self._publish_journal_event("normalizer.unknown_symbol", {"error": str(exc)})
            return []

        payload = raw.get("payload", {})
        if self._exchange == "binance":
            raw_trades = self._extract_binance_trades(payload)
        else:
            raw_trades = self._extract_htx_trades(payload)

        rows: list[dict] = []
        for trade_id, price, quantity, side, trade_time_ms in raw_trades:
            if self._is_duplicate(canonical_symbol, trade_id):
                continue

            trade_time = datetime.fromtimestamp(trade_time_ms / 1000, tz=UTC)
            self._check_gap(canonical_symbol, trade_time)

            rows.append(
                {
                    "time": trade_time,
                    "exchange": self._exchange,
                    "symbol": canonical_symbol,
                    "price": Decimal(str(price)),
                    "quantity": Decimal(str(quantity)),
                    "side": side,
                    "trade_id": trade_id,
                }
            )
        return rows

    @staticmethod
    def _extract_htx_trades(payload: dict) -> list[tuple[str, str, str, str, int]]:
        """`market.<symbol>.trade.detail` (comportement préexistant,
        inchangé par ce correctif) - `tick.data[]` peut contenir
        plusieurs trades agrégés dans un seul message."""
        tick = payload.get("tick", {})
        return [
            (
                str(t["tradeId"]),
                t["price"],
                t["amount"],
                "buy" if t["direction"] == "buy" else "sell",
                t["ts"],
            )
            for t in tick.get("data", [])
        ]

    @staticmethod
    def _extract_binance_trades(payload: dict) -> list[tuple[str, str, str, str, int]]:
        """`<symbol>@trade` (vérifié le 18/08/2026 contre la
        documentation Binance Open Platform, Trade Streams - jamais
        `@aggTrade`, dont les champs diffèrent : pas de `t`/`m`, mais
        `a`/`f`/`l`). Un message = un seul trade, jamais une liste
        agrégée contrairement à HTX.

        `m` ("is the buyer the market maker") détermine le côté
        agresseur : si vrai, l'acheteur était passif (maker) et le
        vendeur agressif -> trade classé SELL ; sinon, BUY - même
        convention que `direction` côté HTX (le côté qui a déclenché
        l'exécution, jamais le côté passif)."""
        if "t" not in payload:
            return []
        side = "sell" if payload.get("m") else "buy"
        return [(str(payload["t"]), payload["p"], payload["q"], side, payload["T"])]

    def normalize_order_book_message(self, raw: dict) -> dict | None:
        """Format spécifique à l'exchange, même principe que
        `normalize_trade_message` ci-dessus - même bug corrigé le
        18/08/2026 : `payload.tick.bids/asks` (HTX) n'existe jamais
        côté Binance, dont le flux `depth20@100ms` porte `bids`/`asks`
        directement à la racine du payload (vérifié le 18/08/2026
        contre la documentation Binance Open Platform, Partial Book
        Depth Streams)."""
        native_symbol = raw["native_symbol"]
        try:
            canonical_symbol = to_canonical(self._exchange, native_symbol)
        except UnknownSymbolError as exc:
            self._publish_journal_event("normalizer.unknown_symbol", {"error": str(exc)})
            return None

        payload = raw.get("payload", {})
        if self._exchange == "binance":
            bids, asks = payload.get("bids"), payload.get("asks")
        else:
            tick = payload.get("tick", {})
            bids, asks = tick.get("bids"), tick.get("asks")

        if bids is None or asks is None:
            return None

        return {
            "time": datetime.now(tz=UTC),
            "exchange": self._exchange,
            "symbol": canonical_symbol,
            "bids": json.dumps(bids[:20]),
            "asks": json.dumps(asks[:20]),
        }

    def _is_duplicate(self, symbol: str, trade_id: str) -> bool:
        cache = self._recent_trade_ids.setdefault(symbol, deque(maxlen=DEDUP_CACHE_SIZE))
        if trade_id in cache:
            return True
        cache.append(trade_id)
        return False

    def _check_gap(self, symbol: str, trade_time: datetime) -> None:
        last_time = self._last_trade_time.get(symbol)
        if last_time is not None:
            gap = (trade_time - last_time).total_seconds()
            if gap > GAP_THRESHOLD_SECONDS:
                self._publish_journal_event(
                    "data.gap_detected",
                    {"exchange": self._exchange, "symbol": symbol, "gap_seconds": gap},
                )
                logger.warning("Trou de données détecté sur %s : %.1fs", symbol, gap)
        self._last_trade_time[symbol] = trade_time


async def main() -> None:
    redis_client = redis.from_url(REDIS_URL)
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)

    def publish_journal_event(event_type: str, payload: dict) -> None:
        asyncio.create_task(
            redis_client.publish(
                JOURNAL_CHANNEL,
                json.dumps(
                    {"source_module": "data_normalizer", "event_type": event_type, "payload": payload}
                ),
            )
        )

    # Un TradeNormalizer par exchange actif (ADR-0012) - jamais un seul
    # "htx" en dur. Le mapping canal -> normaliseur permet de router
    # chaque message vers le bon exchange sans dupliquer la boucle
    # d'écoute Redis.
    normalizers: dict[str, TradeNormalizer] = {
        exchange: TradeNormalizer(exchange=exchange, publish_journal_event=publish_journal_event)
        for exchange in ACTIVE_EXCHANGES
    }

    trade_buffer: list[dict] = []
    depth_buffer: list[dict] = []

    trade_channels = [f"raw:{exchange}:trade" for exchange in ACTIVE_EXCHANGES]
    depth_channels = [f"raw:{exchange}:depth" for exchange in ACTIVE_EXCHANGES]

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(*trade_channels, *depth_channels)

    async def flush_periodically() -> None:
        while True:
            await asyncio.sleep(BATCH_INTERVAL_SECONDS)
            await _flush_trades(db_pool, trade_buffer)
            await _flush_order_book(db_pool, depth_buffer)

    asyncio.create_task(flush_periodically())

    async for message in pubsub.listen():
        if message["type"] != "message":
            continue

        raw = json.loads(message["data"])
        channel = message["channel"].decode("utf-8")
        # Canal attendu : "raw:{exchange}:trade" ou "raw:{exchange}:depth"
        _, exchange, kind = channel.split(":")
        normalizer = normalizers.get(exchange)
        if normalizer is None:
            continue  # exchange retiré de ACTIVE_EXCHANGES depuis le démarrage - message obsolète, ignoré

        if kind == "trade":
            trade_buffer.extend(normalizer.normalize_trade_message(raw))
            if len(trade_buffer) >= BATCH_MAX_SIZE:
                await _flush_trades(db_pool, trade_buffer)

        elif kind == "depth":
            row = normalizer.normalize_order_book_message(raw)
            if row is not None:
                depth_buffer.append(row)
            if len(depth_buffer) >= BATCH_MAX_SIZE:
                await _flush_order_book(db_pool, depth_buffer)


async def _flush_trades(db_pool: asyncpg.Pool, buffer: list[dict]) -> None:
    if not buffer:
        return
    rows = buffer.copy()
    buffer.clear()
    async with db_pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO raw_market_data (time, exchange, symbol, price, quantity, side, trade_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7);
            """,
            [
                (r["time"], r["exchange"], r["symbol"], r["price"], r["quantity"], r["side"], r["trade_id"])
                for r in rows
            ],
        )


async def _flush_order_book(db_pool: asyncpg.Pool, buffer: list[dict]) -> None:
    if not buffer:
        return
    rows = buffer.copy()
    buffer.clear()
    async with db_pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO order_book_snapshots (time, exchange, symbol, bids, asks)
            VALUES ($1, $2, $3, $4, $5);
            """,
            [(r["time"], r["exchange"], r["symbol"], r["bids"], r["asks"]) for r in rows],
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
