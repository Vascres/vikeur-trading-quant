"""Service calibration (ADR-0009, ADR-0015).

Tourne en cycle périodique, persiste des `calibration_runs`, branchées
sur le flux de décision live depuis ADR-0010 (chantier 4) via
`meta_engine/calibration_lookup.py`.

Donnée d'entrée (ADR-0015) : `meta_decisions.fused_score` (le score brut
issu de la fusion multi-moteurs, ADR-0010) - avec repli sur l'ancienne
colonne `decisions.success_probability` pour les décisions historiques
antérieures à ADR-0010 (qui n'ont pas de `meta_decision_id` ; ce champ
portait alors le score brut de l'unique stratégie existante, cf.
ADR-0009 §Contexte). ADR-0009 avait explicitement anticipé que ce point
de branchement changerait au chantier 4 sans que la mécanique de
calibration elle-même ne change - ce correctif honore cette intention
initiale, restée non appliquée jusqu'ici (identifié lors du diagnostic
du deadlock calibration/trades).

Joint aux positions clôturées via `positions.decision_id` (Phase 15)
pour obtenir l'issue réelle de chaque décision.

Fournisseur par défaut (ADR-0015) : `BayesianCalibrationProvider`,
remplace `LogisticCalibrationProvider` (ADR-0009, conservée telle
quelle pour référence historique et comme implémentation alternative
disponible via le contrat `CalibrationProvider` - jamais supprimée, cf.
ADR-0010 §Conséquences pour le précédent de conservation d'un composant
déprécié)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import replace
from decimal import Decimal

import asyncpg
import redis.asyncio as redis

from calibration.bayesian_provider import BayesianCalibrationProvider
from shared.calibration_provider import CalibrationProvider, CalibrationRun
from shared.confidence_lifecycle import COLLECTING, classify_calibration_maturity
from shared.heartbeat import run_heartbeat

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]
JOURNAL_CHANNEL = "events:journal"

CALIBRATION_INTERVAL_SECONDS = int(os.environ.get("CALIBRATION_INTERVAL_SECONDS", str(6 * 3600)))


async def _gather_historical_data(db_pool: asyncpg.Pool) -> tuple[list[float], list[bool], list]:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT COALESCE(md.fused_score, d.success_probability) AS raw_score,
                   p.realized_pnl, p.closed_at
            FROM positions p
            JOIN decisions d ON d.id = p.decision_id
            LEFT JOIN meta_decisions md ON md.id = d.meta_decision_id
            WHERE p.status = 'closed' AND p.decision_id IS NOT NULL
            ORDER BY p.closed_at ASC;
            """
        )
    scores = [float(row["raw_score"]) for row in rows]
    outcomes = [Decimal(str(row["realized_pnl"])) > 0 for row in rows]
    closed_ats = [row["closed_at"] for row in rows]
    return scores, outcomes, closed_ats


async def run_calibration_cycle(
    db_pool: asyncpg.Pool, publish_journal_event, provider: CalibrationProvider | None = None
) -> CalibrationRun:
    provider = provider or BayesianCalibrationProvider()

    scores, outcomes, closed_ats = await _gather_historical_data(db_pool)
    calibration = await provider.calibrate(scores, outcomes)

    if closed_ats:
        calibration = replace(
            calibration, training_period_start=closed_ats[0], training_period_end=closed_ats[-1]
        )

    # ADR-0015 : l'activation n'exige plus `is_validated` (comportement
    # ADR-0009, réservé au mode réel) mais tout niveau de maturité au-delà
    # de `collecting` - c'est-à-dire toute estimation exploitable en mode
    # paper (`preliminary` ou `validated`, ADR-0014). Une tentative qui
    # reste `collecting` (échantillon < 5) ne désactive jamais la
    # précédente calibration active - identique en substance à l'invariant
    # ADR-0009 ("jamais de régression vers 'aucune calibration active' à
    # cause d'un échec ultérieur"), reformulé pour le Confidence Lifecycle.
    maturity = classify_calibration_maturity(calibration)
    should_activate = maturity != COLLECTING

    async with db_pool.acquire() as conn:
        if should_activate:
            await conn.execute("UPDATE calibration_runs SET is_active = FALSE WHERE is_active;")

        await conn.execute(
            """
            INSERT INTO calibration_runs
                (method, training_period_start, training_period_end, sample_size,
                 brier_score, is_validated, is_active, parameters, reason)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9);
            """,
            calibration.method,
            calibration.training_period_start,
            calibration.training_period_end,
            calibration.sample_size,
            calibration.brier_score,
            calibration.is_validated,
            should_activate,
            json.dumps(calibration.parameters),
            calibration.reason,
        )

    publish_journal_event(
        "calibration.run_completed",
        {
            "method": calibration.method,
            "sample_size": calibration.sample_size,
            "is_validated": calibration.is_validated,
            "maturity": maturity,
            "brier_score": calibration.brier_score,
            "reason": calibration.reason,
        },
    )
    return calibration


async def main() -> None:
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    redis_client = redis.from_url(REDIS_URL)
    asyncio.create_task(run_heartbeat())

    def publish_journal_event(event_type: str, payload: dict) -> None:
        asyncio.create_task(
            redis_client.publish(
                JOURNAL_CHANNEL,
                json.dumps(
                    {"source_module": "calibration", "event_type": event_type, "payload": payload},
                    default=str,
                ),
            )
        )

    publish_journal_event("calibration.started", {})

    while True:
        try:
            await run_calibration_cycle(db_pool, publish_journal_event)
        except Exception as exc:  # noqa: BLE001 - ne jamais arrêter la boucle globale
            logger.exception("Erreur lors du cycle de calibration")
            publish_journal_event("calibration.cycle_error", {"error": str(exc)})

        await asyncio.sleep(CALIBRATION_INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
