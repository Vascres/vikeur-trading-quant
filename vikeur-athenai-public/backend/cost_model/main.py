"""Service cost_model (ADR-0016, étendu par ADR-0020 puis par le chantier
CostModel unique du 16/08/2026).

Tourne en cycle périodique (quotidien par défaut - un palier tarifaire
d'exchange ne change pas à la minute, contrairement au carnet d'ordres),
interroge le palier de frais réel de chaque exchange actif
(`ACTIVE_EXCHANGES`, ADR-0012 - jamais HTX en dur, même principe que
`data_collector/main.py`) ainsi que le funding réel des perpétuels quand
un adaptateur futures existe pour cet exchange (ADR-0020), et persiste
le résultat dans `fee_schedule`/`funding_rate_measurements`.
`decision_engine` et `risk_engine` lisent la dernière ligne persistée
(jamais un appel réseau synchrone dans le chemin critique de décision).

Panne de l'API frais : ne bloque jamais le cycle - persiste un repli
documenté et sourcé, par exchange (jamais une valeur inventée, cf.
`cost_model/fee_schedule.py`). Panne de l'API funding : aucun repli
documenté n'a de sens (cf. `cost_model/funding_rate.py`) - le symbole
concerné est simplement omis pour ce cycle, jamais un blocage du reste.

Binance Futures (Étapes 7-8, 16/08/2026) : `BinanceFuturesAdapter`
existe désormais (`data_collector/adapters/binance_futures.py`) et est
enregistré dans `futures_factory` - le funding Binance est donc mesuré
au même titre que HTX, via `cost_model/binance_funding_fetcher.py`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import asyncpg
import redis.asyncio as redis

from cost_model.binance_fee_fetcher import fetch_binance_fee_schedule
from cost_model.binance_funding_fetcher import fetch_binance_funding_rates
from cost_model.htx_fee_fetcher import fetch_htx_fee_schedule
from cost_model.htx_funding_fetcher import fetch_htx_funding_rates
from data_collector.adapters.factory import build_exchange_adapter
from data_collector.adapters.futures_factory import (
    UnknownFuturesExchangeError,
    build_futures_exchange_adapter,
)
from shared.exchange_adapter import ExchangeAdapter
from shared.exchange_config import ACTIVE_EXCHANGES
from shared.futures_adapter import FuturesExchangeAdapter
from shared.heartbeat import run_heartbeat
from shared.symbol_mapping import to_canonical

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
# Correctif du 16/08/2026 (chantier Telegram) : ce module publiait sur
# "journal_events" alors que tous les autres services (10 sur 12,
# execution_engine/decision_engine/risk_engine/... compris) publient sur
# "events:journal" - un vrai canal Redis différent, jamais consommé par
# personne depuis la création de cost_model. Aucun consommateur n'écoutait
# encore ce canal jusqu'ici, donc aucune régression observable, mais tous
# les événements cost_model publiés avant ce correctif n'ont jamais été
# reçus nulle part.
JOURNAL_CHANNEL = "events:journal"

# Quotidien par défaut - un palier de frais ne se recalcule pas plus
# vite que ça en pratique (dépend d'un volume glissant sur 30 jours) ;
# le funding se règle toutes les 8h côté HTX (ADR-0020) - le cycle
# quotidien reste suffisant pour observer sa tendance, pas nécessaire de
# le mesurer plus souvent que les frais pour l'usage actuel (mesure,
# pas encore un agent qui en dépendrait en temps réel - ADR-0021).
COST_MODEL_INTERVAL_SECONDS = int(os.environ.get("COST_MODEL_INTERVAL_SECONDS", "86400"))

DEFAULT_SYMBOLS_NATIVE = "btcusdt,ethusdt,solusdt"

# Un fetcher de frais par exchange enregistré - même principe que
# `data_collector/adapters/factory.py` : ajouter un exchange demain
# consiste à écrire son fetcher puis à l'enregistrer ici, jamais à
# modifier `run_cost_model_cycle`.
_FEE_FETCHERS = {
    "htx": fetch_htx_fee_schedule,
    "binance": fetch_binance_fee_schedule,
}

# Un fetcher de funding par exchange - désormais Binance aussi
# (Étapes 7-8, 16/08/2026 : `BinanceFuturesAdapter` existe et est
# enregistré dans `futures_factory`).
_FUTURES_FUNDING_FETCHERS = {
    "htx": fetch_htx_funding_rates,
    "binance": fetch_binance_funding_rates,
}


def _tracked_symbols_native(exchange: str) -> list[str]:
    """Même convention que `data_collector/main.py::_tracked_symbols`
    (TRACKED_SYMBOLS_HTX, TRACKED_SYMBOLS_BINANCE...) - dupliquée
    plutôt qu'importée : `data_collector` n'expose que ses adaptateurs
    comme surface réutilisable (fabriques), jamais son point d'entrée
    `main.py`."""
    specific = os.environ.get(f"TRACKED_SYMBOLS_{exchange.upper()}")
    if specific is not None:
        return specific.split(",")
    return os.environ.get("TRACKED_SYMBOLS", DEFAULT_SYMBOLS_NATIVE).split(",")


async def run_cost_model_cycle(
    db_pool: asyncpg.Pool,
    exchange: str,
    spot_adapter: ExchangeAdapter,
    futures_adapter: FuturesExchangeAdapter | None,
    publish_journal_event,
) -> None:
    canonical_symbols = [to_canonical(exchange, s) for s in _tracked_symbols_native(exchange)]

    schedules = await _FEE_FETCHERS[exchange](spot_adapter, canonical_symbols)

    funding_rates = []
    if futures_adapter is not None:
        funding_rates = await _FUTURES_FUNDING_FETCHERS[exchange](futures_adapter, canonical_symbols)

    async with db_pool.acquire() as conn:
        for schedule in schedules:
            await conn.execute(
                """
                INSERT INTO fee_schedule (exchange, symbol, maker_fee_bps, taker_fee_bps, source, measured_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (exchange, symbol) DO UPDATE SET
                    maker_fee_bps = EXCLUDED.maker_fee_bps,
                    taker_fee_bps = EXCLUDED.taker_fee_bps,
                    source = EXCLUDED.source,
                    measured_at = EXCLUDED.measured_at;
                """,
                schedule.exchange,
                schedule.symbol,
                schedule.maker_fee_bps,
                schedule.taker_fee_bps,
                schedule.source,
                schedule.measured_at,
            )

        for rate in funding_rates:
            await conn.execute(
                """
                INSERT INTO funding_rate_measurements (exchange, symbol, funding_rate_bps, source, measured_at)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (exchange, symbol) DO UPDATE SET
                    funding_rate_bps = EXCLUDED.funding_rate_bps,
                    source = EXCLUDED.source,
                    measured_at = EXCLUDED.measured_at;
                """,
                rate.exchange,
                rate.symbol,
                rate.funding_rate_bps,
                rate.source,
                rate.measured_at,
            )

    publish_journal_event(
        "cost_model.run_completed",
        {
            "exchange": exchange,
            "symbols": canonical_symbols,
            "sources": {s.symbol: s.source for s in schedules},
            "round_trip_taker_fee_bps": {s.symbol: s.round_trip_taker_fee_bps for s in schedules},
            "funding_rate_bps": {r.symbol: r.funding_rate_bps for r in funding_rates},
        },
    )


async def main() -> None:
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    redis_client = redis.from_url(REDIS_URL)
    asyncio.create_task(run_heartbeat())

    def publish_journal_event(event_type: str, payload: dict) -> None:
        asyncio.create_task(
            redis_client.publish(
                JOURNAL_CHANNEL,
                json.dumps(
                    {"source_module": "cost_model", "event_type": event_type, "payload": payload},
                    default=str,
                ),
            )
        )

    # Un adaptateur par exchange actif, construit une seule fois au
    # démarrage (même durée de vie que le process, comme avant ce
    # chantier) - jamais reconstruit à chaque cycle.
    spot_adapters: dict[str, ExchangeAdapter] = {
        exchange: build_exchange_adapter(exchange)
        for exchange in ACTIVE_EXCHANGES
        if exchange in _FEE_FETCHERS
    }
    futures_adapters: dict[str, FuturesExchangeAdapter] = {}
    for exchange in ACTIVE_EXCHANGES:
        if exchange not in _FUTURES_FUNDING_FETCHERS:
            continue
        try:
            futures_adapters[exchange] = build_futures_exchange_adapter(exchange)
        except UnknownFuturesExchangeError:
            logger.info(
                "Aucun adaptateur futures enregistré pour '%s' - mesure du funding omise pour cet exchange.",
                exchange,
            )

    publish_journal_event("cost_model.started", {"exchanges": list(spot_adapters)})

    while True:
        for exchange, spot_adapter in spot_adapters.items():
            try:
                await run_cost_model_cycle(
                    db_pool, exchange, spot_adapter, futures_adapters.get(exchange), publish_journal_event
                )
            except Exception as exc:
                logger.exception("Erreur lors du cycle cost_model pour '%s'", exchange)
                publish_journal_event("cost_model.cycle_error", {"exchange": exchange, "error": str(exc)})

        await asyncio.sleep(COST_MODEL_INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
