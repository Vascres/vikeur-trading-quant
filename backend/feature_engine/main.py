"""Service feature_engine (Phase 9).

Ne dépend jamais de decision_engine (Phase 2, contrat import-linter).
Lit ohlcv_candles_1m et order_book_snapshots (Phase 6), écrit dans
feature_values en référençant les feature_definition_id validés par
le registre (Phase 9, §3).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime

import asyncpg
import redis.asyncio as redis

from feature_engine.registry import ACTIVE_FEATURES, register_and_verify_features
from shared.exchange_config import ACTIVE_EXCHANGES
from shared.symbol_mapping import BINANCE_NATIVE_TO_CANONICAL, HTX_NATIVE_TO_CANONICAL

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]
JOURNAL_CHANNEL = "events:journal"

COMPUTE_INTERVAL_SECONDS = 60  # aligné sur le rafraîchissement du continuous aggregate (Phase 6)
CANDLE_HISTORY_NEEDED = 25  # >= la plus grande fenêtre utilisée (WINDOW_SIZE=20, +marge - Phase 9 §4)

# Chantier Liquidation Cascade (16/08/2026) - fenêtre de la feature
# liquidation_cascade_intensity. Valeur de départ, jamais calibrée
# empiriquement (aucun historique réel au moment de l'écriture,
# liquidation_ingest vient d'être déployé) - à ajuster une fois
# suffisamment de données de cascades réelles observées.
LIQUIDATION_WINDOW_SECONDS = 300

# Symboles canoniques suivis par exchange (ADR-0012) - jamais un seul
# EXCHANGE/SYMBOLS en dur. Ajouter un exchange à cette liste demande
# d'y ajouter son mapping de symboles (`shared/symbol_mapping.py`).
_SYMBOLS_BY_EXCHANGE = {
    "htx": list(HTX_NATIVE_TO_CANONICAL.values()),
    "binance": list(BINANCE_NATIVE_TO_CANONICAL.values()),
}


async def main() -> None:
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    redis_client = redis.from_url(REDIS_URL)

    def publish_journal_event(event_type: str, payload: dict) -> None:
        asyncio.create_task(
            redis_client.publish(
                JOURNAL_CHANNEL,
                json.dumps({"source_module": "feature_engine", "event_type": event_type, "payload": payload}),
            )
        )

    feature_definition_ids = await register_and_verify_features(db_pool)
    publish_journal_event(
        "feature_engine.started",
        {"features": list(feature_definition_ids.keys()), "exchanges": ACTIVE_EXCHANGES},
    )

    while True:
        for exchange in ACTIVE_EXCHANGES:
            for symbol in _SYMBOLS_BY_EXCHANGE.get(exchange, []):
                try:
                    await _compute_and_store_features(db_pool, exchange, symbol, feature_definition_ids)
                except (
                    Exception
                ) as exc:  # noqa: BLE001 - une erreur sur un symbole ne doit jamais arrêter les autres
                    logger.exception("Erreur de calcul de features pour %s/%s", exchange, symbol)
                    publish_journal_event(
                        "feature_engine.computation_error",
                        {"exchange": exchange, "symbol": symbol, "error": str(exc)},
                    )
        await asyncio.sleep(COMPUTE_INTERVAL_SECONDS)


async def _compute_and_store_features(
    db_pool: asyncpg.Pool, exchange: str, symbol: str, feature_definition_ids: dict[str, int]
) -> None:
    async with db_pool.acquire() as conn:
        candles = await conn.fetch(
            """
            SELECT close, volume FROM ohlcv_candles_1m
            WHERE exchange = $1 AND symbol = $2
            ORDER BY bucket DESC
            LIMIT $3;
            """,
            exchange,
            symbol,
            CANDLE_HISTORY_NEEDED,
        )
        closes = [float(row["close"]) for row in reversed(candles)]
        volumes = [float(row["volume"]) for row in reversed(candles)]

        latest_book = await conn.fetchrow(
            """
            SELECT bids, asks FROM order_book_snapshots
            WHERE exchange = $1 AND symbol = $2
            ORDER BY time DESC
            LIMIT 1;
            """,
            exchange,
            symbol,
        )

        # Chantier Liquidation Cascade (16/08/2026) - fenêtre glissante,
        # jamais un accès horloge dans la feature elle-même (cf.
        # docstring de LiquidationCascadeIntensity) : le filtrage
        # temporel se fait ici, dans l'appelant, exactement comme les
        # candles ci-dessus (ORDER BY ... LIMIT) sont déjà pré-filtrées
        # avant d'atteindre `Momentum.compute`.
        liquidation_rows = await conn.fetch(
            """
            SELECT notional FROM liquidation_events
            WHERE exchange = $1 AND symbol = $2 AND event_time >= now() - make_interval(secs => $3);
            """,
            exchange,
            symbol,
            LIQUIDATION_WINDOW_SECONDS,
        )

    market_data = {"closes": closes, "volumes": volumes}
    market_data["recent_liquidation_notionals"] = [float(row["notional"]) for row in liquidation_rows]
    if latest_book is not None:
        # Cast explicite en float à l'extraction (18/08/2026) - bug réel
        # trouvé en activant Binance pour la première fois : HTX envoie
        # des niveaux de prix/quantité déjà numériques dans son JSON,
        # mais Binance les envoie systématiquement en CHAÎNES DE
        # CARACTÈRES (convention documentée de leur API : "DECIMAL
        # parameters such as price are expected as JSON strings, not
        # floats") - `bids[0][0]` valait donc une str côté Binance,
        # jamais côté HTX, jusqu'ici jamais détecté puisque Binance n'a
        # jamais produit de vraie donnée avant le correctif de
        # data_normalizer. Cassait `SpreadBps.compute` (comparaison
        # `<=`) ET `OrderFlowImbalance.compute` (`sum()` sur des str) -
        # jamais une feature isolée, toutes les features de ce cycle
        # pour ce (exchange, symbole) étaient perdues d'un coup (une
        # seule exception non rattrapée par feature dans la boucle
        # appelante). Corrigé à la source, une seule fois, plutôt que
        # dans chaque feature individuellement.
        raw_bids = json.loads(latest_book["bids"])
        raw_asks = json.loads(latest_book["asks"])
        bids = [(float(price), float(quantity)) for price, quantity in raw_bids]
        asks = [(float(price), float(quantity)) for price, quantity in raw_asks]
        market_data["bids"] = bids
        market_data["asks"] = asks
        if bids and asks:
            market_data["best_bid"] = bids[0][0]
            market_data["best_ask"] = asks[0][0]

    now = datetime.now(tz=UTC)
    rows_to_insert = []
    for feature in ACTIVE_FEATURES:
        value = feature.compute(market_data)
        if value is None:
            continue  # donnée insuffisante - jamais bloquant (Phase 9, contrat Feature)
        rows_to_insert.append((now, feature_definition_ids[feature.metadata.name], exchange, symbol, value))

    if rows_to_insert:
        async with db_pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO feature_values (time, feature_definition_id, exchange, symbol, value)
                VALUES ($1, $2, $3, $4, $5);
                """,
                rows_to_insert,
            )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
