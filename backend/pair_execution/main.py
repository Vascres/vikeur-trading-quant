"""Service pair_execution (ADR-0021) - Pair Execution Engine pour
funding_basis_arbitrage.

Cycle périodique (même patron que `cost_model`/`calibration`) : pour
chaque symbole suivi, vérifie s'il existe une opportunité d'arbitrage
de financement (`funding_rate_measurements`, ADR-0020), l'évalue
(`pair_execution.pair_quality`), et si acceptée, l'exécute - en mode
**paper uniquement** pour l'instant. Le mode réel nécessiterait sa
propre attestation de gouvernance dédiée (même principe que
`futures_real_trading_enabled`, ADR-0018) et le câblage d'ordres FOK
réels à deux jambes - non construit dans ce chantier, cohérent avec la
discipline "paper d'abord" déjà appliquée à chaque nouvelle capacité de
ce projet.

Le mode paper simule un résultat probabiliste par jambe (ADR-0021 §4.7)
- jamais un succès automatique - pour que la machine à états
PARTIAL_EXECUTION soit réellement exercée avant toute activation réelle.

Limitation assumée et documentée, pas cachée : le carnet d'ordres
futures n'est pas encore collecté (`data_collector` ne s'abonne qu'au
flux spot à ce jour) - la jambe futures utilise une probabilité de
remplissage conservatrice documentée en attendant un futur chantier
d'extension de la collecte.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from datetime import UTC, datetime
from decimal import Decimal

import asyncpg
import redis.asyncio as redis

from execution_engine.positions import apply_fill
from pair_execution.liquidity_simulator import estimate_fill_probability
from pair_execution.pair_quality import (
    LegAssessment,
    PairDecisionOutcome,
    assess_pair_opportunity,
)
from pair_execution.state_machine import (
    LegOutcome,
    PairStatus,
    ResolutionAction,
    build_incident_record,
    decide_completion_attempt,
    determine_execution_outcome,
    is_symbol_blocked_by_unresolved_pair,
)
from shared.fee_constants import (
    DOCUMENTED_FALLBACK_FUTURES_TAKER_FEE_BPS,
    DOCUMENTED_FALLBACK_TAKER_FEE_BPS,
)
from shared.heartbeat import run_heartbeat

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
# Correctif du 16/08/2026 (chantier Telegram) : même bug pré-existant
# que cost_model/main.py - ce module (ADR-0021) publiait sur
# "journal_events" au lieu du canal réellement utilisé partout ailleurs,
# "events:journal". Antérieur à cet audit, découvert seulement en
# construisant le service de notifications, qui a besoin d'un canal
# unique et cohérent pour tout entendre.
JOURNAL_CHANNEL = "events:journal"

PAIR_EXECUTION_INTERVAL_SECONDS = int(os.environ.get("PAIR_EXECUTION_INTERVAL_SECONDS", "60"))
TRACKED_SYMBOLS = os.environ.get("TRACKED_SYMBOLS_CANONICAL", "BTC/USDT,ETH/USDT,SOL/USDT").split(",")

STRATEGY_NAME = "funding_basis_arbitrage"
STRATEGY_VERSION = 1

# ADR-0021 : le carnet futures n'est pas encore collecté (cf. docstring
# du module) - probabilité conservatrice documentée en attendant,
# jamais confondue avec une vraie simulation de profondeur.
FUTURES_ORDER_BOOK_UNAVAILABLE_FILL_PROBABILITY = 0.85

# Paramètres de la machine à états (ADR-0021 §4.5) - valeurs de départ
# prudentes, comme chaque autre seuil de ce projet.
MAX_COMPLETION_ATTEMPTS = 2
MAX_EDGE_DEGRADATION_BPS = 5.0

# --- Dimensionnement capital-relatif (correctif du 16/08/2026) ---
#
# Remplace l'ancienne constante `quantity = Decimal("0.01")` appliquée
# uniformément à BTC/ETH/SOL sans rapport avec leurs prix unitaires très
# différents ni avec le capital réellement disponible (à titre d'exemple,
# 0.01 BTC représentait ~630 USD au moment de l'audit, largement au-delà
# d'un compte de quelques centaines de dollars, tandis que 0.01 SOL
# représentait moins de 1 USD, probablement sous le notionnel minimum de
# l'exchange). Même philosophie que
# `risk_engine.rules.position_sizing.MAX_RISK_FRACTION` (2% du capital par
# position), mais dupliquée ici plutôt qu'importée : le contrat
# import-linter 12 interdit tout import de `risk_engine` depuis
# `pair_execution` (ADR-0021 §2 - contournement délibéré de la fusion).
MAX_PAIR_NOTIONAL_FRACTION = Decimal("0.02")

# Notionnel minimum en dessous duquel une jambe n'est pas dimensionnable de
# façon réaliste (bruit d'arrondi, rejet probable par le minimum d'ordre de
# l'exchange). Valeur de sécurité conservatrice documentée - à remplacer
# par les minimums réels HTX/Binance mesurés avant toute activation en
# mode réel (limitation assumée, comme les autres valeurs de ce module).
MIN_LEG_NOTIONAL_USD = Decimal("10")

# Fraîcheur de l'instantané de portefeuille requise pour dimensionner une
# paire - dupliqué de `risk_engine.main.PORTFOLIO_SNAPSHOT_MAX_AGE_SECONDS`
# pour la même raison que ci-dessus (contrat 12).
PORTFOLIO_SNAPSHOT_MAX_AGE_SECONDS = int(os.environ.get("PORTFOLIO_SNAPSHOT_MAX_AGE_SECONDS", "300"))


async def _register_funding_basis_strategy(db_pool: asyncpg.Pool) -> int:
    """`funding_basis_arbitrage` n'est délibérément PAS un `DecisionEngine`
    (ADR-0021 §2, option B) - jamais ajouté à `ACTIVE_STRATEGIES`
    (`strategies/registry.py`), jamais appelé par la boucle de fusion de
    `decision_engine`. Cette fonction l'enregistre séparément dans
    `strategies` uniquement pour satisfaire la contrainte d'intégrité de
    `decisions` (`strategy_id IS NOT NULL OR meta_decision_id IS NOT NULL`,
    ADR-0010) et pour que la traçabilité/explicabilité déjà construite
    fonctionne sans modification."""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO strategies (name, version, parameters, is_active, logic_hash)
            VALUES ($1, $2, $3, TRUE, $4)
            ON CONFLICT (name, version) DO UPDATE SET is_active = TRUE
            RETURNING id;
            """,
            STRATEGY_NAME,
            STRATEGY_VERSION,
            json.dumps({}),
            "pair_execution_engine_v1",
        )
    return row["id"]


def _parse_order_book_levels(raw_levels) -> list[tuple[Decimal, Decimal]]:
    return [(Decimal(str(price)), Decimal(str(quantity))) for price, quantity in raw_levels]


async def _fetch_spot_order_book_levels(
    db_pool: asyncpg.Pool, exchange: str, symbol: str, side: str
) -> list[tuple[Decimal, Decimal]]:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT bids, asks FROM order_book_snapshots
            WHERE exchange = $1 AND symbol = $2
            ORDER BY time DESC LIMIT 1;
            """,
            exchange,
            symbol,
        )
    if row is None:
        return []
    raw_levels = json.loads(row["asks"]) if side == "buy" else json.loads(row["bids"])
    return _parse_order_book_levels(raw_levels)


async def _fetch_funding_rate_bps(db_pool: asyncpg.Pool, exchange: str, symbol: str) -> float | None:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT funding_rate_bps FROM funding_rate_measurements WHERE exchange = $1 AND symbol = $2;",
            exchange,
            symbol,
        )
    return row["funding_rate_bps"] if row is not None else None


async def _fetch_available_capital(db_pool: asyncpg.Pool, exchange: str) -> Decimal | None:
    """Capital de référence pour le dimensionnement - même source que
    `risk_engine.main` (dernier instantané `portfolio_snapshots`), jamais
    une constante figée. Retourne `None` si l'instantané est absent ou
    trop ancien : jamais une valeur par défaut silencieuse (même principe
    que `PortfolioUnavailableError` dans `risk_engine`, dupliqué ici sans
    y être couplé - contrat import-linter 12)."""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT total_value_reference_currency, taken_at FROM portfolio_snapshots
            WHERE exchange = $1 AND market_type IS NULL
            ORDER BY taken_at DESC LIMIT 1;
            """,
            exchange,
        )
    if row is None:
        return None
    snapshot_age_seconds = (datetime.now(tz=UTC) - row["taken_at"]).total_seconds()
    if snapshot_age_seconds > PORTFOLIO_SNAPSHOT_MAX_AGE_SECONDS:
        return None
    return Decimal(str(row["total_value_reference_currency"]))


async def _fetch_reference_price(db_pool: asyncpg.Pool, exchange: str, symbol: str) -> Decimal | None:
    """Prix de référence pour convertir un notionnel cible en quantité,
    avant même de connaître le sens de la jambe spot (qui dépend du signe
    du funding, déterminé plus tard dans `build_pair_assessment`). Le
    côté "ask" du carnet sert de convention pour ce seul besoin de
    dimensionnement - le prix d'exécution réel est re-lu depuis le carnet
    dans `build_pair_assessment`, jamais celui-ci."""
    levels = await _fetch_spot_order_book_levels(db_pool, exchange, symbol, "buy")
    if not levels:
        return None
    price, _ = levels[0]
    return price if price > 0 else None


async def _compute_pair_quantity(db_pool: asyncpg.Pool, exchange: str, symbol: str) -> Decimal | None:
    """Dimensionne la quantité (identique pour les deux jambes, structure
    cash-and-carry classique) sur `MAX_PAIR_NOTIONAL_FRACTION` du capital
    disponible. Retourne `None` - jamais une estimation dégradée - si le
    capital est inconnu/périmé, si le prix de référence est indisponible,
    ou si le notionnel résultant est sous `MIN_LEG_NOTIONAL_USD`."""
    available_capital = await _fetch_available_capital(db_pool, exchange)
    if available_capital is None:
        return None

    reference_price = await _fetch_reference_price(db_pool, exchange, symbol)
    if reference_price is None:
        return None

    target_notional = available_capital * MAX_PAIR_NOTIONAL_FRACTION
    if target_notional < MIN_LEG_NOTIONAL_USD:
        return None

    return target_notional / reference_price


async def _fetch_open_pair_statuses(db_pool: asyncpg.Pool, exchange: str, symbol: str) -> list[PairStatus]:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT status FROM pair_decisions
            WHERE exchange = $1 AND symbol = $2
              AND status NOT IN ('both_filled', 'both_rejected', 'resolved');
            """,
            exchange,
            symbol,
        )
    return [PairStatus(r["status"]) for r in rows]


async def build_pair_assessment(db_pool: asyncpg.Pool, exchange: str, symbol: str, target_quantity: Decimal):
    """Construit l'évaluation complète d'une opportunité (ADR-0021 §4.1-4.3)
    - retourne `None` si le funding n'est pas encore mesuré pour ce
    symbole (jamais un blocage, juste rien à évaluer ce cycle)."""
    funding_rate_bps = await _fetch_funding_rate_bps(db_pool, exchange, symbol)
    if funding_rate_bps is None:
        return None

    spot_side = "sell" if funding_rate_bps > 0 else "buy"
    spot_levels = await _fetch_spot_order_book_levels(db_pool, exchange, symbol, spot_side)
    spot_fill_probability = estimate_fill_probability(spot_levels, target_quantity)
    spot_price, _ = spot_levels[0] if spot_levels else (Decimal(0), Decimal(0))
    spot_slippage_bps = 0.0  # approximé par la marche de carnet côté risk_engine à l'exécution réelle

    leg_spot = LegAssessment(
        market_type="spot",
        fee_bps=DOCUMENTED_FALLBACK_TAKER_FEE_BPS,
        slippage_bps=spot_slippage_bps,
        fill_probability=spot_fill_probability,
    )
    leg_futures = LegAssessment(
        market_type="futures_perpetual",
        fee_bps=DOCUMENTED_FALLBACK_FUTURES_TAKER_FEE_BPS,
        slippage_bps=0.0,
        fill_probability=FUTURES_ORDER_BOOK_UNAVAILABLE_FILL_PROBABILITY,
    )

    # Coût de compensation estimé : approximé par le double du coût de
    # transaction d'une jambe (ouverture + fermeture immédiate en cas de
    # compensation) - une estimation de départ documentée, pas mesurée,
    # à affiner une fois des incidents réels accumulés (ADR-0021 §5).
    compensation_cost_estimate_bps = 2 * (leg_spot.fee_bps + leg_futures.fee_bps)

    assessment = assess_pair_opportunity(
        funding_rate_bps=funding_rate_bps,
        leg_a=leg_spot,
        leg_b=leg_futures,
        compensation_cost_estimate_bps=compensation_cost_estimate_bps,
    )
    return assessment, spot_side, spot_price


async def _simulate_leg_outcome(fill_probability: float, random_source=random.random) -> LegOutcome:
    """ADR-0021 §4.7 : jamais un succès automatique en paper - tire un
    résultat probabiliste cohérent avec la probabilité de remplissage
    estimée, pour que le chemin PARTIAL_EXECUTION soit réellement
    exercé avant toute activation réelle."""
    return LegOutcome.FILLED if random_source() < fill_probability else LegOutcome.REJECTED


async def _persist_pair_assessment(db_pool: asyncpg.Pool, exchange: str, symbol: str, assessment) -> int:
    """Persiste l'évaluation, que la décision soit ACCEPT ou REJECT
    (corrige un écart découvert au déploiement : le schéma prévoyait
    dès le départ `decision IN ('accept', 'reject')`, mais la première
    version de cette fonction n'enregistrait que les paires acceptées -
    un rejet redevenait alors invisible, silencieux, jamais consultable
    après coup, contrairement à l'intention initiale)."""
    async with db_pool.acquire() as conn:
        pair_row = await conn.fetchrow(
            """
            INSERT INTO pair_decisions
                (exchange, symbol, funding_rate_bps, gross_edge_bps, fees_bps, slippage_bps,
                 net_edge_bps, execution_probability, execution_risk, pair_quality_score,
                 decision, status, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            RETURNING id;
            """,
            exchange,
            symbol,
            assessment.gross_edge_bps,
            assessment.gross_edge_bps,
            assessment.fees_bps,
            assessment.slippage_bps,
            assessment.net_edge_bps,
            assessment.execution_probability,
            assessment.execution_risk.value,
            assessment.pair_quality_score,
            assessment.decision.value,
            PairStatus.EXECUTING.value,
            datetime.now(tz=UTC),
        )
    return pair_row["id"]


async def execute_pair_opportunity_paper(
    db_pool: asyncpg.Pool,
    *,
    exchange: str,
    symbol: str,
    strategy_id: int,
    assessment,
    spot_side: str,
    spot_price: Decimal,
    quantity: Decimal,
    publish_journal_event,
    pair_decision_id: int,
    random_source=random.random,
) -> int:
    """Exécute (simule, en paper) une opportunité déjà acceptée -
    orchestre la machine à états complète (ADR-0021 §4.5), y compris
    la gestion PARTIAL_EXECUTION. `pair_decision_id` est déjà créé par
    `_persist_pair_assessment` avant l'appel - cette fonction ne fait
    plus que le mettre à jour, jamais une seconde insertion."""
    futures_side = "sell" if spot_side == "buy" else "buy"  # la jambe futures est toujours le sens opposé

    leg_a_outcome = await _simulate_leg_outcome(_leg_probability_for(assessment, "spot"), random_source)
    leg_b_outcome = await _simulate_leg_outcome(
        _leg_probability_for(assessment, "futures_perpetual"), random_source
    )

    outcome_status = determine_execution_outcome(leg_a_outcome, leg_b_outcome)

    if outcome_status == PairStatus.BOTH_FILLED:
        await _open_both_legs(
            db_pool,
            exchange,
            symbol,
            strategy_id,
            pair_decision_id,
            spot_side,
            futures_side,
            spot_price,
            quantity,
        )
        await _update_pair_status(db_pool, pair_decision_id, PairStatus.BOTH_FILLED, resolved=True)
        publish_journal_event(
            "pair_execution.both_filled",
            {"pair_decision_id": pair_decision_id, "exchange": exchange, "symbol": symbol},
        )
        return pair_decision_id

    if outcome_status == PairStatus.BOTH_REJECTED:
        await _update_pair_status(db_pool, pair_decision_id, PairStatus.BOTH_REJECTED, resolved=True)
        publish_journal_event(
            "pair_execution.both_rejected",
            {"pair_decision_id": pair_decision_id, "exchange": exchange, "symbol": symbol},
        )
        return pair_decision_id

    # PARTIAL_EXECUTION - le cœur du chantier (ADR-0021 §4.5-§4.6).
    await _update_pair_status(db_pool, pair_decision_id, PairStatus.PARTIAL_EXECUTION)
    filled_leg = "spot" if leg_a_outcome == LegOutcome.FILLED else "futures_perpetual"
    missing_leg = "futures_perpetual" if filled_leg == "spot" else "spot"

    # Ouvre immédiatement la jambe qui a réussi (le marché ne l'attend pas).
    filled_side = spot_side if filled_leg == "spot" else futures_side
    await _open_single_leg(
        db_pool,
        exchange,
        symbol,
        strategy_id,
        pair_decision_id,
        filled_leg,
        filled_side,
        spot_price,
        quantity,
    )

    completion_decision = decide_completion_attempt(
        current_net_edge_bps=assessment.net_edge_bps,  # ré-évaluation réelle laissée à un futur raffinement
        original_net_edge_bps=assessment.net_edge_bps,
        max_edge_degradation_bps=MAX_EDGE_DEGRADATION_BPS,
        attempts_made=0,
        max_attempts=MAX_COMPLETION_ATTEMPTS,
    )

    residual_notional = float(quantity * spot_price)

    if completion_decision.should_attempt:
        await _update_pair_status(db_pool, pair_decision_id, PairStatus.COMPLETING_MISSING_LEG)
        retry_outcome = await _simulate_leg_outcome(
            _leg_probability_for(assessment, missing_leg), random_source
        )
        if retry_outcome == LegOutcome.FILLED:
            missing_side = futures_side if missing_leg == "futures_perpetual" else spot_side
            await _open_single_leg(
                db_pool,
                exchange,
                symbol,
                strategy_id,
                pair_decision_id,
                missing_leg,
                missing_side,
                spot_price,
                quantity,
            )
            await _record_incident(
                db_pool,
                pair_decision_id,
                filled_leg,
                missing_leg,
                residual_notional,
                ResolutionAction.COMPLETED_MISSING_LEG,
                realized_cost_bps=0.0,
            )
            await _update_pair_status(db_pool, pair_decision_id, PairStatus.BOTH_FILLED, resolved=True)
            publish_journal_event(
                "pair_execution.partial_execution_completed",
                {"pair_decision_id": pair_decision_id, "exchange": exchange, "symbol": symbol},
            )
            return pair_decision_id

    # Complétion refusée ou échouée - compensation (ADR-0021 §4.5).
    await _update_pair_status(db_pool, pair_decision_id, PairStatus.COMPENSATING)
    realized_cost_bps = (
        assessment.fees_bps / 2
    )  # coût de la jambe fermée immédiatement, approximation de départ
    await _close_single_leg(db_pool, exchange, symbol, filled_leg, filled_side, spot_price, quantity)
    await _record_incident(
        db_pool,
        pair_decision_id,
        filled_leg,
        missing_leg,
        residual_notional,
        ResolutionAction.COMPENSATED_OPEN_LEG,
        realized_cost_bps=realized_cost_bps,
    )
    await _update_pair_status(db_pool, pair_decision_id, PairStatus.RESOLVED, resolved=True)
    publish_journal_event(
        "pair_execution.partial_execution_compensated",
        {
            "pair_decision_id": pair_decision_id,
            "exchange": exchange,
            "symbol": symbol,
            "realized_cost_bps": realized_cost_bps,
        },
    )
    return pair_decision_id


def _leg_probability_for(assessment, market_type: str) -> float:
    """Reconstruit la probabilité de remplissage individuelle d'une jambe
    à partir de l'évaluation déjà calculée - `assess_pair_opportunity`
    ne conserve que le produit (`execution_probability`), pas chaque
    jambe séparément ; ce raccourci sera nettoyé une fois le simulateur
    étendu pour porter les deux probabilités individuelles explicitement."""
    return assessment.execution_probability**0.5  # approximation symétrique de départ


async def _update_pair_status(
    db_pool: asyncpg.Pool, pair_decision_id: int, status: PairStatus, resolved: bool = False
) -> None:
    async with db_pool.acquire() as conn:
        if resolved:
            await conn.execute(
                "UPDATE pair_decisions SET status = $1, resolved_at = $2 WHERE id = $3;",
                status.value,
                datetime.now(tz=UTC),
                pair_decision_id,
            )
        else:
            await conn.execute(
                "UPDATE pair_decisions SET status = $1 WHERE id = $2;", status.value, pair_decision_id
            )


async def _insert_leg_decision(
    db_pool: asyncpg.Pool, exchange: str, symbol: str, strategy_id: int, pair_decision_id: int, side: str
) -> int:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO decisions
                (strategy_id, exchange, symbol, time, success_probability, expected_value,
                 risk_reward_ratio, verdict, feature_snapshot_ids, suggested_side, pair_decision_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, 'signal', '{}', $8, $9)
            RETURNING id;
            """,
            strategy_id,
            exchange,
            symbol,
            datetime.now(tz=UTC),
            0.0,  # non disponible - ADR-0021 ne produit pas de probabilité calibrée
            0.0,
            0.0,
            side,
            pair_decision_id,
        )
    return row["id"]


async def _open_single_leg(
    db_pool, exchange, symbol, strategy_id, pair_decision_id, market_type, side, price, quantity
) -> None:
    decision_id = await _insert_leg_decision(db_pool, exchange, symbol, strategy_id, pair_decision_id, side)
    await apply_fill(
        db_pool,
        exchange=exchange,
        symbol=symbol,
        execution_mode="paper",
        side=side,
        filled_price=price,
        filled_quantity=quantity,
        decision_id=decision_id,
        market_type=market_type,
    )


async def _open_both_legs(
    db_pool, exchange, symbol, strategy_id, pair_decision_id, spot_side, futures_side, price, quantity
) -> None:
    await _open_single_leg(
        db_pool, exchange, symbol, strategy_id, pair_decision_id, "spot", spot_side, price, quantity
    )
    await _open_single_leg(
        db_pool,
        exchange,
        symbol,
        strategy_id,
        pair_decision_id,
        "futures_perpetual",
        futures_side,
        price,
        quantity,
    )


async def _close_single_leg(db_pool, exchange, symbol, market_type, filled_side, price, quantity) -> None:
    """Clôture immédiate de la jambe déjà ouverte (ADR-0021 §4.5,
    compensation) - sens opposé au remplissage initial, priorité à la
    vitesse (revenir à plat), pas à l'optimisation du prix."""
    closing_side = "sell" if filled_side == "buy" else "buy"
    await apply_fill(
        db_pool,
        exchange=exchange,
        symbol=symbol,
        execution_mode="paper",
        side=closing_side,
        filled_price=price,
        filled_quantity=quantity,
        market_type=market_type,
    )


async def _record_incident(
    db_pool: asyncpg.Pool,
    pair_decision_id: int,
    filled_leg: str,
    missing_leg: str,
    residual_exposure_notional: float,
    resolution_action: ResolutionAction,
    realized_cost_bps: float | None,
) -> None:
    record = build_incident_record(
        filled_leg_market_type=filled_leg,
        missing_leg_market_type=missing_leg,
        residual_exposure_notional=residual_exposure_notional,
        resolution_action=resolution_action,
        realized_cost_bps=realized_cost_bps,
    )
    now = datetime.now(tz=UTC)
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO pair_incidents
                (pair_decision_id, incident_type, filled_leg, missing_leg, residual_exposure_notional,
                 resolution_action, realized_cost_bps, detected_at, resolved_at)
            VALUES ($1, 'partial_execution', $2, $3, $4, $5, $6, $7, $8);
            """,
            pair_decision_id,
            record.filled_leg,
            record.missing_leg,
            record.residual_exposure_notional,
            record.resolution_action.value,
            record.realized_cost_bps,
            now,
            now,
        )


async def run_pair_execution_cycle(
    db_pool: asyncpg.Pool, strategy_id: int, publish_journal_event, exchange: str = "htx"
) -> None:
    for symbol in TRACKED_SYMBOLS:
        open_statuses = await _fetch_open_pair_statuses(db_pool, exchange, symbol)
        if is_symbol_blocked_by_unresolved_pair(open_statuses):
            publish_journal_event("pair_execution.symbol_blocked", {"exchange": exchange, "symbol": symbol})
            continue

        quantity = await _compute_pair_quantity(db_pool, exchange, symbol)
        if quantity is None:
            publish_journal_event(
                "pair_execution.symbol_skipped_sizing_unavailable",
                {"exchange": exchange, "symbol": symbol},
            )
            continue

        result = await build_pair_assessment(db_pool, exchange, symbol, quantity)
        if result is None:
            continue
        assessment, spot_side, spot_price = result

        pair_decision_id = await _persist_pair_assessment(db_pool, exchange, symbol, assessment)

        if assessment.decision != PairDecisionOutcome.ACCEPT:
            await _update_pair_status(db_pool, pair_decision_id, PairStatus.RESOLVED, resolved=True)
            publish_journal_event(
                "pair_execution.rejected",
                {
                    "pair_decision_id": pair_decision_id,
                    "exchange": exchange,
                    "symbol": symbol,
                    "pair_quality_score": assessment.pair_quality_score,
                    "execution_risk": assessment.execution_risk.value,
                },
            )
            continue

        await execute_pair_opportunity_paper(
            db_pool,
            exchange=exchange,
            symbol=symbol,
            strategy_id=strategy_id,
            assessment=assessment,
            spot_side=spot_side,
            spot_price=spot_price,
            quantity=quantity,
            publish_journal_event=publish_journal_event,
            pair_decision_id=pair_decision_id,
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
                    {"source_module": "pair_execution", "event_type": event_type, "payload": payload},
                    default=str,
                ),
            )
        )

    strategy_id = await _register_funding_basis_strategy(db_pool)
    publish_journal_event("pair_execution.started", {"strategy_id": strategy_id})

    while True:
        try:
            await run_pair_execution_cycle(db_pool, strategy_id, publish_journal_event)
        except Exception as exc:
            logger.exception("Erreur lors du cycle pair_execution")
            publish_journal_event("pair_execution.cycle_error", {"error": str(exc)})

        await asyncio.sleep(PAIR_EXECUTION_INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
