"""Service portfolio_aggregator (ADR-0003, ADR-0007).

Remplace `STARTING_CAPITAL` : interroge périodiquement le
`PortfolioProvider` actif, persiste un instantané valorisé
(`portfolio_snapshots`), et détecte les écarts inattendus par rapport à
l'évolution attendue depuis le P&L réalisé interne - cf. événement
`ReconciliationDiscrepancyDetected` (Event Architecture Spec, §3).

Tourne comme un service dédié (conteneur `portfolio`, cf.
`docker-compose.yml`) - `risk_engine` ne fait jamais lui-même l'appel
réseau vers l'exchange, il lit uniquement le dernier instantané déjà
persisté (un appel réseau dans le chemin critique de décision serait une
source de latence et de fragilité inutile - Architecture Cible V2, §4.1).

Le mode d'exécution est lu depuis `execution_mode_state` (ADR-0004,
ADR-0008) via `shared.execution_mode_state.fetch_current_mode` - plus
jamais depuis une variable d'environnement.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from decimal import Decimal

import asyncpg
import redis.asyncio as redis

from data_collector.adapters.factory import build_exchange_adapter
from data_collector.adapters.futures_factory import build_futures_exchange_adapter
from portfolio.futures_provider import FuturesPortfolioProvider
from portfolio.generic_provider import GenericPortfolioProvider
from shared.exchange_config import ACTIVE_EXCHANGES, get_futures_exchange_credentials
from shared.execution_mode_state import fetch_current_mode
from shared.futures_adapter import SupportsAccountBalance
from shared.heartbeat import run_heartbeat
from shared.portfolio_provider import PortfolioProvider

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]
JOURNAL_CHANNEL = "events:journal"

SNAPSHOT_INTERVAL_SECONDS = int(os.environ.get("PORTFOLIO_SNAPSHOT_INTERVAL_SECONDS", "60"))

# Tolérance absolue (devise de référence) avant de considérer un écart
# comme une divergence à signaler plutôt qu'un simple bruit d'arrondi/
# frais non capturés (ADR-0007) - configurable, jamais codée en dur sans
# justification (Development Standards §1).
RECONCILIATION_TOLERANCE = Decimal(os.environ.get("PORTFOLIO_RECONCILIATION_TOLERANCE", "1"))


async def main() -> None:
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
    redis_client = redis.from_url(REDIS_URL)
    asyncio.create_task(run_heartbeat())

    def publish_journal_event(event_type: str, payload: dict) -> None:
        asyncio.create_task(
            redis_client.publish(
                JOURNAL_CHANNEL,
                json.dumps(
                    {"source_module": "portfolio_aggregator", "event_type": event_type, "payload": payload},
                    default=str,
                ),
            )
        )

    # Un adaptateur + un fournisseur par exchange actif (ADR-0012) - jamais
    # un seul HTX en dur. Ajouter un exchange = l'ajouter à
    # ACTIVE_EXCHANGES, jamais modifier ce service.
    adapters = {
        exchange: build_exchange_adapter(exchange, journal_publisher=publish_journal_event)
        for exchange in ACTIVE_EXCHANGES
    }
    providers: dict[str, PortfolioProvider] = {
        exchange: GenericPortfolioProvider(exchange, adapter, db_pool)
        for exchange, adapter in adapters.items()
    }

    # Solde de marge futures (17/08/2026) - un fournisseur SUPPLÉMENTAIRE
    # par exchange, uniquement si (a) des clés futures sont réellement
    # configurées pour cet exchange ET (b) son adaptateur sait interroger
    # un solde (`SupportsAccountBalance` - Binance aujourd'hui, jamais HTX
    # tant que son endpoint n'est pas vérifié). Jamais construit à
    # l'aveugle : un adaptateur sans clés lèverait à chaque cycle.
    futures_adapters = {}
    futures_providers: dict[str, PortfolioProvider] = {}
    for exchange in ACTIVE_EXCHANGES:
        futures_api_key, futures_api_secret = get_futures_exchange_credentials(exchange)
        if not futures_api_key or not futures_api_secret:
            continue
        futures_adapter = build_futures_exchange_adapter(exchange)
        if not isinstance(futures_adapter, SupportsAccountBalance):
            continue
        futures_adapters[exchange] = futures_adapter
        futures_providers[exchange] = FuturesPortfolioProvider(exchange, futures_adapter, db_pool)

    publish_journal_event(
        "portfolio_aggregator.started",
        {"exchanges": list(providers.keys()), "futures_exchanges": list(futures_providers.keys())},
    )

    # Liste de (exchange, provider, is_futures) plutôt qu'une fusion de
    # dictionnaires par nom d'exchange (17/08/2026) : `providers` et
    # `futures_providers` peuvent partager la MÊME clé (ex. "binance"
    # actif en spot et en futures) - un `{**providers, **futures_providers}`
    # aurait silencieusement écrasé le fournisseur spot par le futures,
    # supprimant tout instantané spot pour cet exchange.
    all_providers = [(exchange, provider, False) for exchange, provider in providers.items()] + [
        (exchange, provider, True) for exchange, provider in futures_providers.items()
    ]

    try:
        while True:
            for exchange, provider, is_futures in all_providers:
                try:
                    await take_and_check_snapshot(db_pool, provider, publish_journal_event, is_futures)
                except (
                    Exception
                ) as exc:  # noqa: BLE001 - une erreur sur un exchange ne doit jamais arrêter les autres
                    logger.exception(
                        "Erreur lors de la prise d'instantané du portefeuille (%s, futures=%s)",
                        exchange,
                        is_futures,
                    )
                    publish_journal_event(
                        "portfolio_aggregator.snapshot_error",
                        {
                            "exchange": exchange,
                            "market_type": "futures_perpetual" if is_futures else "spot",
                            "error": str(exc),
                        },
                    )

            await asyncio.sleep(SNAPSHOT_INTERVAL_SECONDS)
    finally:
        # Même raison qu'`all_providers` ci-dessus : jamais une fusion de
        # dictionnaires par nom d'exchange, qui fuirait la connexion HTTP
        # de l'un des deux adaptateurs partageant la même clé.
        for adapter in list(adapters.values()) + list(futures_adapters.values()):
            await adapter.close()


async def take_and_check_snapshot(
    db_pool: asyncpg.Pool, provider: PortfolioProvider, publish_journal_event, is_futures: bool = False
) -> None:
    """Prend un instantané, le persiste, et compare avec l'instantané
    précédent + le P&L réalisé interne depuis lors - toute divergence au-delà
    de la tolérance est journalisée, jamais absorbée silencieusement
    (Architecture Cible V2, §4.1 ; principe directeur 3).

    `is_futures` (17/08/2026) : détermine le `market_type` de l'instantané
    ET filtre la réconciliation sur les positions du MÊME marché
    (`positions.market_type`, toujours explicite depuis ADR-0018/0019) -
    un solde futures ne doit jamais être réconcilié contre du P&L spot,
    ni l'inverse."""
    snapshot = await provider.take_snapshot()
    market_type = "futures_perpetual" if is_futures else "spot"

    async with db_pool.acquire() as conn:
        previous = await conn.fetchrow(
            """
            SELECT id, taken_at, total_value_reference_currency FROM portfolio_snapshots
            WHERE exchange = $1 AND market_type IS NOT DISTINCT FROM $2
            ORDER BY taken_at DESC LIMIT 1;
            """,
            provider.exchange_name,
            market_type if is_futures else None,
        )

        snapshot_id = await conn.fetchval(
            """
            INSERT INTO portfolio_snapshots
                (exchange, taken_at, reference_currency, total_value_reference_currency, market_type)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id;
            """,
            snapshot.exchange,
            snapshot.taken_at,
            snapshot.reference_currency,
            snapshot.total_value_reference_currency,
            market_type if is_futures else None,
        )

        for asset, amount in snapshot.balances.items():
            await conn.execute(
                """
                INSERT INTO portfolio_snapshot_balances (portfolio_snapshot_id, asset, amount)
                VALUES ($1, $2, $3);
                """,
                snapshot_id,
                asset,
                amount,
            )

        if previous is not None:
            current_execution_mode = await fetch_current_mode(conn)
            realized_pnl_row = await conn.fetchrow(
                """
                SELECT COALESCE(SUM(realized_pnl), 0) AS total FROM positions
                WHERE status = 'closed' AND execution_mode = $1 AND market_type = $2 AND closed_at > $3;
                """,
                current_execution_mode,
                market_type,
                previous["taken_at"],
            )
            expected_total = Decimal(str(previous["total_value_reference_currency"])) + Decimal(
                str(realized_pnl_row["total"])
            )
            delta = snapshot.total_value_reference_currency - expected_total

            if abs(delta) > RECONCILIATION_TOLERANCE:
                publish_journal_event(
                    "portfolio_aggregator.reconciliation_discrepancy_detected",
                    {
                        "exchange": provider.exchange_name,
                        "market_type": market_type,
                        "expected_total": str(expected_total),
                        "observed_total": str(snapshot.total_value_reference_currency),
                        "delta": str(delta),
                    },
                )

    publish_journal_event(
        "portfolio_aggregator.snapshot_taken",
        {
            "exchange": provider.exchange_name,
            "market_type": market_type,
            "total": str(snapshot.total_value_reference_currency),
        },
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
