"""Orchestrateur final Décision -> Risque -> Exécution (Phase 13).

Vit délibérément dans execution_engine : c'est la couche la plus haute
(Phase 2/5, contrats import-linter), donc la seule autorisée à importer
risk_engine. risk_engine, lui, n'importe jamais execution_engine
(voir risk_engine/main.py).

Le mode d'exécution (ADR-0004, ADR-0008) est relu à chaque itération de
la boucle, jamais figé une seule fois au démarrage - un changement de
mode approuvé par execution_mode_governance doit prendre effet sans
redémarrer ce service.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import asyncpg
import redis.asyncio as redis

from data_collector.adapters.factory import build_exchange_adapter
from data_collector.adapters.futures_factory import (
    UnknownFuturesExchangeError,
    build_futures_exchange_adapter,
)
from execution_engine.factory import get_execution_mode
from execution_engine.reconciliation import reconcile_open_positions, reconcile_pending_orders
from shared.heartbeat import run_heartbeat
from risk_engine.main import evaluate_pending_decisions
from shared.exchange_config import ACTIVE_EXCHANGES
from shared.execution_mode_state import get_current_mode

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]
JOURNAL_CHANNEL = "events:journal"
LOOP_INTERVAL_SECONDS = 15


async def main() -> None:
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    redis_client = redis.from_url(REDIS_URL)
    asyncio.create_task(run_heartbeat())

    def publish_journal_event(event_type: str, payload: dict) -> None:
        asyncio.create_task(
            redis_client.publish(
                JOURNAL_CHANNEL,
                json.dumps(
                    {"source_module": "execution_engine", "event_type": event_type, "payload": payload},
                    default=str,
                ),
            )
        )

    # Reconstruction d'état au démarrage (Phase 5, §3.2) - avant toute
    # nouvelle décision, on sait exactement où en sont positions et ordres.
    open_positions = await reconcile_open_positions(db_pool)
    pending_orders = await reconcile_pending_orders(db_pool)
    publish_journal_event(
        "execution_engine.started",
        {"open_positions": len(open_positions), "pending_orders": len(pending_orders)},
    )

    # Construits dès le démarrage (Phase 12, §5) - un par exchange actif
    # (ADR-0012), nécessaires dès que le mode réel est atteint,
    # indépendamment du mode courant au démarrage (ADR-0008 : le mode
    # peut changer sans redémarrage de ce service).
    exchange_adapters = {
        exchange: build_exchange_adapter(exchange, journal_publisher=publish_journal_event)
        for exchange in ACTIVE_EXCHANGES
    }

    # ADR-0018/0019 : parallèle et indépendant - un exchange sans
    # adaptateur futures enregistré (fabrique) est simplement absent de
    # ce dict, jamais une erreur au démarrage (le futures reste
    # optionnel, gouverné par FUTURES_ROUTING_ENABLED + l'attestation
    # dédiée, jamais requis pour que le spot fonctionne).
    futures_exchange_adapters = {}
    for exchange in ACTIVE_EXCHANGES:
        try:
            futures_exchange_adapters[exchange] = build_futures_exchange_adapter(exchange)
        except UnknownFuturesExchangeError:
            continue

    try:
        while True:
            try:
                current_mode = await get_current_mode(db_pool)
                execution_mode = get_execution_mode(
                    current_mode,
                    db_pool,
                    exchange_adapters,
                    futures_exchange_adapters,
                    publish_journal_event,
                )

                outcomes = await evaluate_pending_decisions(db_pool, redis_client, publish_journal_event)
                for outcome in outcomes:
                    if outcome.passed and outcome.suggested_quantity is not None:
                        await execution_mode.execute(
                            risk_check_id=outcome.final_check_id,
                            decision_id=outcome.decision_id,
                            exchange=outcome.exchange,
                            symbol=outcome.symbol,
                            side=outcome.suggested_side,
                            quantity=outcome.suggested_quantity,
                            price=outcome.current_price,
                            market_type=outcome.market_type,
                        )
                        publish_journal_event(
                            "execution_engine.order_executed",
                            {
                                "decision_id": outcome.decision_id,
                                "exchange": outcome.exchange,
                                "symbol": outcome.symbol,
                                "side": outcome.suggested_side,
                                "quantity": outcome.suggested_quantity,
                                "price": outcome.current_price,
                                "market_type": outcome.market_type,
                                "execution_mode": current_mode,
                            },
                        )
            except Exception as exc:  # noqa: BLE001 - ne jamais arrêter la boucle globale
                logger.exception("Erreur dans la boucle d'orchestration")
                publish_journal_event("execution_engine.loop_error", {"error": str(exc)})

            await asyncio.sleep(LOOP_INTERVAL_SECONDS)
    finally:
        for adapter in exchange_adapters.values():
            await adapter.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
