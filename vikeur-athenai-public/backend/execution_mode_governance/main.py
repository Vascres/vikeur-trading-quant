"""Gouvernance du mode d'exécution (ADR-0004, ADR-0008).

Remplace `EXECUTION_MODE` comme variable d'environnement : le mode
courant est une entité en base (`execution_mode_state`), modifiable
exclusivement via `request_mode_change()` ci-dessous. Seule la
transition vers le mode `real` (« Live » dans le vocabulaire de la
mission - cf. limitation assumée en ADR-0008 sur la terminologie) est
soumise à des prérequis automatiques, une double confirmation, et une
phrase de confirmation explicite - conformément au principe directeur 5
(le passage à un niveau de risque supérieur est un acte humain gouverné).

Toute transition vers un mode qui n'augmente pas le risque (ex. real ->
paper) est autorisée immédiatement, sans prérequis : il doit toujours
être possible de réduire le risque sans délai.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import asyncpg

from execution_mode_governance.checks.capital_allocation_configured import CapitalAllocationConfiguredCheck
from execution_mode_governance.checks.exchange_api_operational import ExchangeApiOperationalCheck
from execution_mode_governance.checks.kill_switch_inactive import KillSwitchInactiveCheck
from execution_mode_governance.checks.live_eligible_strategy_exists import LiveEligibleStrategyExistsCheck
from execution_mode_governance.checks.minimum_duration import MinimumContinuousModeDurationCheck
from execution_mode_governance.checks.minimum_trade_count import MinimumTradeCountCheck
from execution_mode_governance.checks.non_negative_performance import NonNegativePerformanceCheck
from execution_mode_governance.checks.positive_exchange_balance import PositiveExchangeBalanceCheck
from execution_mode_governance.checks.recent_attestation import RecentAttestationCheck
from shared.exchange_config import ACTIVE_EXCHANGES
from shared.execution_mode_state import fetch_current_mode
from shared.governance_check import GovernanceCheckResult, GovernanceContext

logger = logging.getLogger(__name__)

# Dupliqué plutôt que centralisé - même convention déjà en place dans
# risk_engine/main.py, monitoring/main.py, api/main.py (chacun définit
# sa propre copie de cette clé Redis plutôt qu'un import croisé).
KILL_SWITCH_REDIS_KEY = "risk:kill_switch"

# Statuts de Strategy Lifecycle (Étape 3) éligibles au mode réel - copié
# de `strategy_lifecycle.states.LIVE_ELIGIBLE_STATUSES` plutôt qu'importé
# (`execution_mode_governance` reste un module de gouvernance isolé,
# contrat import-linter 9 - jamais un chemin détourné vers un autre
# service, la donnée est lue en SQL direct comme partout ailleurs dans
# ce projet).
LIVE_ELIGIBLE_LIFECYCLE_STATUSES = ("validated", "production")

# Seule transition soumise à gouvernance stricte - cf. docstring ci-dessus.
GOVERNANCE_GATED_MODE = "real"
VALID_MODES = {"backtest", "paper", "real"}

# Doit être saisie explicitement par l'opérateur pour confirmer le passage
# en argent réel (Architecture Cible V2, §5.2) - jamais acceptée par défaut.
CONFIRMATION_PHRASE = "ACTIVER LIVE"

ACTIVE_GOVERNANCE_CHECKS = [
    MinimumContinuousModeDurationCheck(),
    MinimumTradeCountCheck(),
    NonNegativePerformanceCheck(),
    ExchangeApiOperationalCheck(),
    RecentAttestationCheck("kill_switch_tested", "Kill switch testé"),
    RecentAttestationCheck("backups_verified", "Sauvegardes vérifiées"),
    RecentAttestationCheck("monitoring_active", "Monitoring actif"),
    # Étape 6 (16/08/2026, "Mur de Fer") - les 4 prérequis de la
    # conception validée qui n'étaient pas encore couverts par les
    # règles ci-dessus (Check 1 "clés exchange valides" est déjà couvert
    # par ExchangeApiOperationalCheck - un instantané de portefeuille
    # récent prouve que l'authentification a fonctionné, jamais dupliqué).
    KillSwitchInactiveCheck(),
    CapitalAllocationConfiguredCheck(),
    PositiveExchangeBalanceCheck(),
    LiveEligibleStrategyExistsCheck(),
]


@dataclass(frozen=True)
class PrerequisiteEvaluation:
    target_mode: str
    overall_passed: bool
    results: list[GovernanceCheckResult]


@dataclass(frozen=True)
class ModeChangeResult:
    accepted: bool
    new_mode: str | None
    reason: str | None
    evaluation: PrerequisiteEvaluation | None


async def _build_governance_context(
    db_pool: asyncpg.Pool, redis_client, target_mode: str
) -> GovernanceContext:
    async with db_pool.acquire() as conn:
        current_mode = await fetch_current_mode(conn)

        # Le début du segment continu courant est l'horodatage de la
        # dernière ligne dont le mode diffère du mode courant, plus une
        # ligne (ou la toute première ligne si le mode courant a été le
        # seul mode depuis le début de l'historique).
        last_different = await conn.fetchrow(
            """
            SELECT changed_at FROM execution_mode_state
            WHERE mode != $1
            ORDER BY changed_at DESC
            LIMIT 1;
            """,
            current_mode,
        )
        if last_different is not None:
            segment_start_row = await conn.fetchrow(
                """
                SELECT changed_at FROM execution_mode_state
                WHERE mode = $1 AND changed_at > $2
                ORDER BY changed_at ASC
                LIMIT 1;
                """,
                current_mode,
                last_different["changed_at"],
            )
        else:
            segment_start_row = await conn.fetchrow(
                "SELECT MIN(changed_at) AS changed_at FROM execution_mode_state WHERE mode = $1;",
                current_mode,
            )
        segment_start = segment_start_row["changed_at"]

        now = datetime.now(tz=UTC)
        continuous_duration_seconds = (now - segment_start).total_seconds()

        trade_count_row = await conn.fetchrow(
            """
            SELECT COUNT(*) AS count, COALESCE(SUM(realized_pnl), 0) AS total_pnl
            FROM positions
            WHERE status = 'closed' AND execution_mode = $1 AND closed_at >= $2;
            """,
            current_mode,
            segment_start,
        )

        # Tous les exchanges actifs doivent avoir un instantané de
        # portefeuille récent pour que "l'API exchange est opérationnelle"
        # soit vraie (ADR-0012) - la fraîcheur retenue est celle du pire
        # cas (l'exchange le moins à jour), jamais une moyenne qui
        # masquerait un exchange en panne. Étape 6 : le même instantané
        # sert aussi à vérifier le solde positif et l'allocation
        # configurée, exchange par exchange, même logique "pire cas".
        portfolio_age: float | None = None
        exchange_balance_positive = True
        for governed_exchange in ACTIVE_EXCHANGES:
            # `market_type IS NULL` (17/08/2026) : le mur d'allocation et
            # la fraîcheur de gouvernance ne concernent que le solde SPOT
            # - un solde de marge futures ne doit jamais s'y substituer.
            portfolio_row = await conn.fetchrow(
                """
                SELECT taken_at, total_value_reference_currency FROM portfolio_snapshots
                WHERE exchange = $1 AND market_type IS NULL
                ORDER BY taken_at DESC LIMIT 1;
                """,
                governed_exchange,
            )
            if portfolio_row is None:
                portfolio_age = None
                exchange_balance_positive = False
                break
            age = (now - portfolio_row["taken_at"]).total_seconds()
            portfolio_age = age if portfolio_age is None else max(portfolio_age, age)
            if Decimal(str(portfolio_row["total_value_reference_currency"])) <= 0:
                exchange_balance_positive = False

        # Étape 5 : une allocation doit exister pour CHAQUE exchange actif.
        capital_allocation_configured = True
        for governed_exchange in ACTIVE_EXCHANGES:
            allocation_row = await conn.fetchrow(
                "SELECT 1 FROM capital_allocation_config WHERE exchange = $1 LIMIT 1;",
                governed_exchange,
            )
            if allocation_row is None:
                capital_allocation_configured = False
                break

        # Étape 3 : au moins une stratégie VALIDATED ou PRODUCTION.
        live_eligible_row = await conn.fetchrow(
            "SELECT 1 FROM strategy_lifecycle_state WHERE status = ANY($1) LIMIT 1;",
            list(LIVE_ELIGIBLE_LIFECYCLE_STATUSES),
        )
        has_live_eligible_strategy = live_eligible_row is not None

        attestation_rows = await conn.fetch(
            """
            SELECT DISTINCT ON (key) key, attested_at FROM governance_attestations
            ORDER BY key, attested_at DESC;
            """
        )
        attestations = {row["key"]: row["attested_at"] for row in attestation_rows}

    # Étape 6 : le kill switch vit dans Redis (`risk:kill_switch`), pas
    # en base - même clé que risk_engine/main.py, monitoring/main.py,
    # api/main.py (convention déjà établie : chaque module en garde sa
    # propre copie plutôt qu'un import centralisé).
    kill_switch_raw = await redis_client.get(KILL_SWITCH_REDIS_KEY)
    kill_switch_active = kill_switch_raw is not None and kill_switch_raw == b"1"

    return GovernanceContext(
        target_mode=target_mode,
        current_mode=current_mode,
        evaluated_at=now,
        continuous_mode_duration_seconds=continuous_duration_seconds,
        trade_count_since_mode_start=trade_count_row["count"],
        realized_pnl_since_mode_start=Decimal(str(trade_count_row["total_pnl"])),
        portfolio_snapshot_age_seconds=portfolio_age,
        attestations=attestations,
        kill_switch_active=kill_switch_active,
        capital_allocation_configured=capital_allocation_configured,
        exchange_balance_positive=exchange_balance_positive,
        has_live_eligible_strategy=has_live_eligible_strategy,
    )


async def evaluate_prerequisites(
    db_pool: asyncpg.Pool, redis_client, target_mode: str
) -> PrerequisiteEvaluation:
    """Évalue les prérequis pour `target_mode`. Retourne toujours
    `overall_passed=True` sans exécuter aucune règle si `target_mode` n'est
    pas le mode gouverné (`real`) - conformément au principe qu'une
    réduction de risque n'est jamais bloquée."""
    if target_mode != GOVERNANCE_GATED_MODE:
        return PrerequisiteEvaluation(target_mode=target_mode, overall_passed=True, results=[])

    context = await _build_governance_context(db_pool, redis_client, target_mode)
    results = [rule.check(context) for rule in ACTIVE_GOVERNANCE_CHECKS]
    overall_passed = all(r.passed for r in results)
    return PrerequisiteEvaluation(target_mode=target_mode, overall_passed=overall_passed, results=results)


async def request_mode_change(
    db_pool: asyncpg.Pool,
    redis_client,
    target_mode: str,
    requested_by: str,
    confirmation_phrase: str | None,
    publish_journal_event,
) -> ModeChangeResult:
    """Point d'entrée unique pour tout changement de mode - jamais un
    UPDATE direct sur `execution_mode_state` ailleurs dans le code."""
    if target_mode not in VALID_MODES:
        reason = f"Mode invalide : '{target_mode}'. Attendu : {VALID_MODES}."
        publish_journal_event(
            "execution_mode_governance.change_rejected",
            {"target_mode": target_mode, "reason": reason},
        )
        return ModeChangeResult(accepted=False, new_mode=None, reason=reason, evaluation=None)

    async with db_pool.acquire() as conn:
        current_mode = await fetch_current_mode(conn)

    if current_mode == target_mode:
        return ModeChangeResult(
            accepted=True, new_mode=target_mode, reason="Déjà dans ce mode.", evaluation=None
        )

    if target_mode == GOVERNANCE_GATED_MODE:
        if confirmation_phrase != CONFIRMATION_PHRASE:
            reason = "Phrase de confirmation manquante ou incorrecte."
            publish_journal_event(
                "execution_mode_governance.change_rejected",
                {"target_mode": target_mode, "reason": reason, "requested_by": requested_by},
            )
            return ModeChangeResult(accepted=False, new_mode=None, reason=reason, evaluation=None)

        evaluation = await evaluate_prerequisites(db_pool, redis_client, target_mode)
        if not evaluation.overall_passed:
            unmet = [r.check_name for r in evaluation.results if not r.passed]
            reason = f"Prérequis non satisfaits : {', '.join(unmet)}."
            publish_journal_event(
                "execution_mode_governance.change_rejected",
                {
                    "target_mode": target_mode,
                    "requested_by": requested_by,
                    "unmet_prerequisites": unmet,
                    "results": [
                        {"check": r.check_name, "passed": r.passed, "reason": r.reason}
                        for r in evaluation.results
                    ],
                },
            )
            return ModeChangeResult(accepted=False, new_mode=None, reason=reason, evaluation=evaluation)
    else:
        evaluation = PrerequisiteEvaluation(target_mode=target_mode, overall_passed=True, results=[])

    async with db_pool.acquire() as conn:
        governance_snapshot = json.dumps(
            {
                "results": [
                    {"check": r.check_name, "passed": r.passed, "reason": r.reason}
                    for r in evaluation.results
                ]
            },
            default=str,
        )
        await conn.execute(
            """
            INSERT INTO execution_mode_state
                (mode, previous_mode, authorized_by, confirmation_phrase_provided, governance_snapshot)
            VALUES ($1, $2, $3, $4, $5::jsonb);
            """,
            target_mode,
            current_mode,
            requested_by,
            confirmation_phrase == CONFIRMATION_PHRASE,
            governance_snapshot,
        )

    publish_journal_event(
        "execution_mode_governance.mode_changed",
        {"previous_mode": current_mode, "new_mode": target_mode, "authorized_by": requested_by},
    )
    return ModeChangeResult(accepted=True, new_mode=target_mode, reason=None, evaluation=evaluation)


async def get_status(db_pool: asyncpg.Pool, redis_client) -> dict:
    """Agrégat consommé par l'API/dashboard (GET /execution-mode)."""
    async with db_pool.acquire() as conn:
        current_mode = await fetch_current_mode(conn)
        history = await conn.fetch(
            """
            SELECT mode, previous_mode, changed_at, authorized_by
            FROM execution_mode_state
            ORDER BY changed_at DESC
            LIMIT 20;
            """
        )

    evaluation = await evaluate_prerequisites(db_pool, redis_client, GOVERNANCE_GATED_MODE)
    return {
        "current_mode": current_mode,
        "history": [dict(row) for row in history],
        "live_prerequisites": {
            "overall_passed": evaluation.overall_passed,
            "results": [
                {"check": r.check_name, "passed": r.passed, "reason": r.reason} for r in evaluation.results
            ],
        },
    }
