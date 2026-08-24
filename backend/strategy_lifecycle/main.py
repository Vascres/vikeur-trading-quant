"""Service strategy_lifecycle (Étape 3 du plan validé le 16/08/2026).

Cycle périodique (horaire par défaut, cf. mandat : "un process batch
léger toutes les heures") : pour chaque stratégie active, recalcule les
métriques glissantes sur ses derniers trades clôturés, et applique une
transition d'éviction ou de résurrection si les seuils de
`eviction_rules` le justifient. Isolé du flux de décision live (contrat
import-linter 13, même principe que `cost_model`/`calibration`) -
`decision_engine` lit `strategy_lifecycle_state` en SQL direct, jamais
via un import de ce package.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import asyncpg
import redis.asyncio as redis

from shared.exchange_config import ACTIVE_EXCHANGES
from shared.heartbeat import run_heartbeat
from strategy_lifecycle.eviction_rules import (
    MIN_QUARANTINE_SAMPLE,
    determine_eviction_transition,
    determine_resurrection_transition,
)
from strategy_lifecycle.metrics import compute_lifecycle_metrics
from strategy_lifecycle.repository import (
    apply_transition,
    ensure_lifecycle_row,
    fetch_active_strategy_ids,
    fetch_lifecycle_status,
    fetch_recent_closed_trades,
    fetch_reference_capital,
    fetch_transitioned_at,
)
from strategy_lifecycle.states import EVICTION_ELIGIBLE_STATUSES, RESURRECTION_ELIGIBLE_STATUSES

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
# Correctif du 16/08/2026 (chantier Telegram) : ce module (créé à
# l'Étape 3) publiait sur "journal_events" au lieu de "events:journal",
# le canal réellement utilisé par tous les autres services - copié par
# erreur du même mauvais exemple que cost_model/main.py (cf. son propre
# correctif), jamais vérifié contre la convention dominante du reste du
# dépôt à l'époque.
JOURNAL_CHANNEL = "events:journal"

# Horaire par défaut (mandat §3 : "process batch léger toutes les
# heures") - un cycle plus fréquent n'apporterait rien tant que le
# rythme de clôture des trades reste de l'ordre de la minute/heure, pas
# de la seconde.
STRATEGY_LIFECYCLE_INTERVAL_SECONDS = int(os.environ.get("STRATEGY_LIFECYCLE_INTERVAL_SECONDS", "3600"))

EVICTION_WINDOW_SIZE = 30  # aligné sur eviction_rules.MIN_SAMPLE_FOR_EVICTION


async def evaluate_strategy(
    db_pool: asyncpg.Pool, strategy_id: int, exchange: str, publish_journal_event
) -> None:
    await ensure_lifecycle_row(db_pool, strategy_id)
    current_status = await fetch_lifecycle_status(db_pool, strategy_id)
    if current_status is None:
        logger.warning(
            "Aucun statut de lifecycle pour la stratégie %s après initialisation - cycle omis.", strategy_id
        )
        return

    if current_status in EVICTION_ELIGIBLE_STATUSES:
        trades = await fetch_recent_closed_trades(db_pool, strategy_id, limit=EVICTION_WINDOW_SIZE)
        metrics = compute_lifecycle_metrics(trades)
        allocated_capital = await fetch_reference_capital(db_pool, exchange)

        if allocated_capital is not None:
            transition = determine_eviction_transition(current_status, metrics, allocated_capital)
            if transition is not None:
                new_status, reason = transition
                await _apply_and_publish(
                    db_pool, strategy_id, current_status, new_status, reason, metrics, publish_journal_event
                )
                return
        else:
            publish_journal_event(
                "strategy_lifecycle.capital_reference_unavailable",
                {"strategy_id": strategy_id, "exchange": exchange},
            )

    if current_status in RESURRECTION_ELIGIBLE_STATUSES:
        since = await fetch_transitioned_at(db_pool, strategy_id)
        quarantine_trades = await fetch_recent_closed_trades(
            db_pool, strategy_id, limit=MIN_QUARANTINE_SAMPLE, since=since
        )
        quarantine_metrics = compute_lifecycle_metrics(quarantine_trades)
        transition = determine_resurrection_transition(current_status, quarantine_metrics)
        if transition is not None:
            new_status, reason = transition
            await _apply_and_publish(
                db_pool,
                strategy_id,
                current_status,
                new_status,
                reason,
                quarantine_metrics,
                publish_journal_event,
            )


async def _apply_and_publish(
    db_pool: asyncpg.Pool,
    strategy_id: int,
    previous_status: str,
    new_status: str,
    reason: str,
    metrics,
    publish_journal_event,
) -> None:
    await apply_transition(
        db_pool,
        strategy_id,
        previous_status,
        new_status,
        reason,
        metrics.ev_net_bps,
        metrics.cumulative_pnl,
        metrics.profit_factor,
        metrics.sample_size,
    )
    publish_journal_event(
        "strategy_lifecycle.transition",
        {
            "strategy_id": strategy_id,
            "previous_status": previous_status,
            "new_status": new_status,
            "reason": reason,
            "ev_net_bps": metrics.ev_net_bps,
            "sample_size": metrics.sample_size,
        },
    )


async def run_strategy_lifecycle_cycle(db_pool: asyncpg.Pool, publish_journal_event) -> None:
    strategy_ids = await fetch_active_strategy_ids(db_pool)
    # ADR-0012 : le capital de référence est propre à un exchange - la
    # première entrée d'ACTIVE_EXCHANGES sert de référence unique tant
    # qu'aucune allocation par stratégie n'existe (même repli documenté
    # que `eviction_rules.determine_eviction_transition`, à revoir une
    # fois l'Étape 5 (Dual Portfolio) livrée).
    exchange = ACTIVE_EXCHANGES[0] if ACTIVE_EXCHANGES else "htx"

    for strategy_id in strategy_ids:
        try:
            await evaluate_strategy(db_pool, strategy_id, exchange, publish_journal_event)
        except Exception as exc:
            logger.exception("Erreur d'évaluation du lifecycle pour la stratégie %s", strategy_id)
            publish_journal_event(
                "strategy_lifecycle.evaluation_error", {"strategy_id": strategy_id, "error": str(exc)}
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
                    {"source_module": "strategy_lifecycle", "event_type": event_type, "payload": payload},
                    default=str,
                ),
            )
        )

    publish_journal_event("strategy_lifecycle.started", {})

    while True:
        try:
            await run_strategy_lifecycle_cycle(db_pool, publish_journal_event)
        except Exception as exc:
            logger.exception("Erreur lors du cycle strategy_lifecycle")
            publish_journal_event("strategy_lifecycle.cycle_error", {"error": str(exc)})

        await asyncio.sleep(STRATEGY_LIFECYCLE_INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
