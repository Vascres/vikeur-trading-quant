"""Service risk_engine (Phase 13).

Correction architecturale importante : ce module N'IMPORTE JAMAIS
execution_engine (violerait l'ordre des couches défini en Phase 2/5 -
execution_engine est la couche la plus haute, elle peut appeler
risk_engine, jamais l'inverse). Ce module évalue les règles et écrit
`risk_checks` ; c'est `execution_engine/main.py` (Phase 13, orchestrateur
final) qui appelle `evaluate_pending_decisions` puis déclenche
l'exécution si le verdict est favorable.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import asyncpg

from risk_engine.rules.daily_loss_limit import DailyLossLimitRule
from risk_engine.rules.futures_notional_exposure_cap import FuturesNotionalExposureCapRule
from risk_engine.rules.kill_switch import KillSwitchRule
from risk_engine.rules.liquidity_slippage_fees import LiquiditySlippageFeesRule
from risk_engine.rules.max_consecutive_loss import MaxConsecutiveLossRule
from risk_engine.rules.max_exposure import MaxExposureRule
from risk_engine.rules.position_sizing import PositionSizingRule
from risk_engine.rules.spot_no_shorting import SpotNoShortingRule
from shared.execution_mode_state import fetch_current_mode
from shared.risk_rule import RiskContext
from shared.strategy import Side

logger = logging.getLogger(__name__)

KILL_SWITCH_REDIS_KEY = "risk:kill_switch"
CONSECUTIVE_LOSS_LOOKBACK = 10

# Fraîcheur maximale tolérée pour le dernier instantané de portefeuille
# (ADR-0003/0007) - au-delà, le capital réel est considéré inconnu et
# toute décision est bloquée par sécurité (principe directeur 3 : la
# vérité vient de l'exchange, jamais d'une hypothèse par défaut).
PORTFOLIO_SNAPSHOT_MAX_AGE_SECONDS = int(os.environ.get("PORTFOLIO_SNAPSHOT_MAX_AGE_SECONDS", "300"))

# ADR-0019 : désactivé par défaut - tant que non activé explicitement,
# aucune décision SELL sans position détenue ne peut jamais être routée
# vers le futures, quel que soit le reste du code déployé. Le seul
# interrupteur qui garantit qu'ADR-0018/0019 ne changent rien au
# comportement actuel au déploiement.
FUTURES_ROUTING_ENABLED = os.environ.get("FUTURES_ROUTING_ENABLED", "false").lower() == "true"


def determine_market_type(
    suggested_side: Side,
    existing_spot_quantity: Decimal,
    existing_futures_quantity: Decimal,
    futures_routing_enabled: bool = FUTURES_ROUTING_ENABLED,
) -> str:
    """Détermine le marché à utiliser pour cette décision (ADR-0019).

    Fonction pure, testable en isolation - aucun accès DB/horloge.

    Priorité à une position futures déjà ouverte (§2, ADR-0019) : une
    position longue et une position courte sur le même symbole ne sont
    jamais fongibles, jamais sommées - rester sur le marché de la
    position déjà ouverte plutôt que de recalculer un routage à chaque
    décision.
    """
    if existing_futures_quantity > 0:
        return "futures_perpetual"
    if existing_spot_quantity > 0:
        return "spot"
    if suggested_side == Side.SELL and futures_routing_enabled:
        return "futures_perpetual"
    return "spot"


# Ordre fixe (Phase 13, §6 ; Phase 15, §4) : position_sizing doit tourner
# avant les règles qui dépendent de la quantité ; spot_no_shorting ne
# dépend que du côté suggéré, peut tourner tôt.
#
# Correctif du 19/08/2026 (bug réel trouvé le soir même de l'activation
# de FUTURES_ROUTING_ENABLED - ADR-0019) : FuturesNotionalExposureCapRule
# était placée AVANT PositionSizingRule, en contradiction directe avec
# l'invariant énoncé juste au-dessus - chaque décision futures échouait
# systématiquement avec "Aucune quantité dimensionnée à vérifier",
# jamais détecté avant faute de décision futures réelle ayant atteint
# le Risk Engine (le flag était resté désactivé jusqu'à ce soir).
ACTIVE_RULES = [
    KillSwitchRule(),
    SpotNoShortingRule(),
    PositionSizingRule(),
    FuturesNotionalExposureCapRule(),
    MaxExposureRule(),
    DailyLossLimitRule(),
    MaxConsecutiveLossRule(),
    LiquiditySlippageFeesRule(),
]


class PortfolioUnavailableError(RuntimeError):
    """Levée quand aucun instantané de portefeuille suffisamment frais
    n'est disponible pour l'exchange concerné (ADR-0003/0007). Le capital
    réel est alors considéré inconnu, et toute décision doit être bloquée
    par sécurité (principe directeur 3 : la vérité vient de l'exchange,
    jamais d'une hypothèse par défaut) - jamais silencieusement ignorée."""


@dataclass(frozen=True)
class RiskOutcome:
    """Résultat d'une évaluation, suffisant pour que l'orchestrateur
    (execution_engine/main.py) décide d'exécuter ou non - sans jamais
    avoir besoin d'importer execution_engine depuis ce module.
    """

    decision_id: int
    final_check_id: int
    passed: bool
    exchange: str
    symbol: str
    suggested_side: str
    suggested_quantity: Decimal | None
    current_price: Decimal
    market_type: str = "spot"


async def evaluate_pending_decisions(
    db_pool: asyncpg.Pool, redis_client, publish_journal_event
) -> list[RiskOutcome]:
    """Évalue toutes les décisions en attente, écrit `risk_checks`, et
    retourne les résultats pour que l'appelant décide de l'exécution.
    """
    async with db_pool.acquire() as conn:
        pending_decisions = await conn.fetch(
            """
            SELECT d.id, d.exchange, d.symbol, d.success_probability, d.expected_value,
                   d.risk_reward_ratio, d.suggested_side, d.market_type
            FROM decisions d
            WHERE d.verdict = 'signal'
              AND NOT EXISTS (SELECT 1 FROM risk_checks rc WHERE rc.decision_id = d.id)
            ORDER BY d.time ASC
            LIMIT 20;
            """
        )

    outcomes = []
    for decision in pending_decisions:
        outcome = await _evaluate_decision(db_pool, redis_client, decision, publish_journal_event)
        outcomes.append(outcome)
    return outcomes


async def _evaluate_decision(db_pool, redis_client, decision, publish_journal_event) -> RiskOutcome:
    try:
        context = await _build_risk_context(db_pool, redis_client, decision)
    except PortfolioUnavailableError as exc:
        return await _record_blocked_outcome(db_pool, decision, publish_journal_event, reason=str(exc))

    results = [rule.check(context) for rule in ACTIVE_RULES]
    overall_passed = all(r.passed for r in results)

    async with db_pool.acquire() as conn:
        for result in results:
            await conn.execute(
                """
                INSERT INTO risk_checks (decision_id, rule_name, passed, reason)
                VALUES ($1, $2, $3, $4);
                """,
                decision["id"],
                result.rule_name,
                result.passed,
                result.reason,
            )

        final_check_id = await conn.fetchval(
            """
            INSERT INTO risk_checks (decision_id, rule_name, passed, reason)
            VALUES ($1, 'FINAL_VERDICT', $2, $3)
            RETURNING id;
            """,
            decision["id"],
            overall_passed,
            "Toutes les règles validées." if overall_passed else "Au moins une règle a échoué (voir détail).",
        )

    publish_journal_event(
        "risk_engine.decision_evaluated",
        {
            "decision_id": decision["id"],
            "symbol": decision["symbol"],
            "passed": overall_passed,
            "results": [{"rule": r.rule_name, "passed": r.passed, "reason": r.reason} for r in results],
        },
    )

    return RiskOutcome(
        decision_id=decision["id"],
        final_check_id=final_check_id,
        passed=overall_passed,
        exchange=decision["exchange"],
        symbol=decision["symbol"],
        suggested_side=decision["suggested_side"],
        suggested_quantity=context.suggested_quantity,
        current_price=context.current_price,
        market_type=context.market_type,
    )


async def _record_blocked_outcome(db_pool, decision, publish_journal_event, reason: str) -> RiskOutcome:
    """Trace un blocage dû à un capital réel inconnu comme n'importe quel
    autre échec de règle (jamais une exception qui remonterait
    silencieusement ou ferait planter la boucle globale) - visible dans
    `risk_checks` et l'explicabilité au même titre qu'une règle classique."""
    async with db_pool.acquire() as conn:
        final_check_id = await conn.fetchval(
            """
            INSERT INTO risk_checks (decision_id, rule_name, passed, reason)
            VALUES ($1, 'FINAL_VERDICT', FALSE, $2)
            RETURNING id;
            """,
            decision["id"],
            reason,
        )

    publish_journal_event(
        "risk_engine.decision_evaluated",
        {
            "decision_id": decision["id"],
            "symbol": decision["symbol"],
            "passed": False,
            "results": [{"rule": "PORTFOLIO_UNAVAILABLE", "passed": False, "reason": reason}],
        },
    )

    return RiskOutcome(
        decision_id=decision["id"],
        final_check_id=final_check_id,
        passed=False,
        exchange=decision["exchange"],
        symbol=decision["symbol"],
        suggested_side=decision["suggested_side"],
        suggested_quantity=None,
        current_price=Decimal("0"),
    )


async def _fetch_paper_available_capital(conn: asyncpg.Connection, market_type: str) -> Decimal:
    """Capital du Paper Portfolio (Étape 4, 16/08/2026 ; scindé en deux
    pools indépendants le 18/08/2026) - totalement indépendant du solde
    réel de l'exchange (`portfolio_snapshots`). Capital initial le plus
    récemment configuré (`paper_capital_config`) plus le P&L réalisé
    simulé depuis cette configuration - poser une nouvelle ligne
    réinitialise le capital de référence sans jamais effacer
    l'historique des trades déjà simulés (Règle Absolue du mandat :
    conserver trades/décisions/performances).

    Deux pools séparés depuis le 18/08/2026 (mandat : "je veux être en
    mesure de voir que le capital du paper trading spot ou futures
    augmente ou diminue... séparément") - un seul pool PAR market_type,
    PARTAGÉ entre tous les exchanges (décision confirmée explicitement,
    pas un pool par exchange). `market_type` reçu ici est toujours une
    valeur littérale ('spot' ou 'futures_perpetual', jamais None -
    `determine_market_type` et le routage explicite du chantier
    Liquidation Cascade ne retournent jamais autre chose) ; la
    conversion vers la convention NULL=spot de `paper_capital_config`
    (même pattern que `decisions.market_type`,
    `portfolio_snapshots.market_type`) se fait ici, en interne.

    Avant l'Étape 4, une décision évaluée en mode paper dimensionnait
    sa position sur le solde RÉEL de l'exchange (même requête que le
    mode réel, sans distinction) - ce n'était pas la séparation étanche
    que le mandat demande (§7-9)."""
    config_row = await conn.fetchrow(
        """
        SELECT initial_capital, set_at FROM paper_capital_config
        WHERE market_type IS NOT DISTINCT FROM $1
        ORDER BY set_at DESC LIMIT 1;
        """,
        market_type if market_type == "futures_perpetual" else None,
    )
    if config_row is None:
        raise PortfolioUnavailableError(
            f"Aucune configuration de capital Paper trouvée pour le marché '{market_type}' "
            "(paper_capital_config) - le capital virtuel est considéré inconnu, jamais une "
            "valeur par défaut silencieuse."
        )

    pnl_since_config_row = await conn.fetchrow(
        """
        SELECT COALESCE(SUM(realized_pnl), 0) AS total FROM positions
        WHERE execution_mode = 'paper' AND status = 'closed' AND market_type = $1 AND closed_at > $2;
        """,
        market_type,
        config_row["set_at"],
    )
    return Decimal(str(config_row["initial_capital"])) + Decimal(str(pnl_since_config_row["total"]))


async def _fetch_real_available_capital(conn: asyncpg.Connection, exchange: str) -> Decimal:
    """Capital réel (ADR-0003/0007), désormais réduit par le "mur
    d'allocation" (Étape 5, 16/08/2026, `capital_allocation_config`) -
    `risk_engine` n'expose plus jamais le solde entier de l'exchange par
    défaut implicite, seulement la fraction explicitement autorisée.

    Aucune configuration d'allocation pour cet exchange = capital
    considéré inconnu, même traitement bloquant qu'un instantané de
    portefeuille absent/périmé (`PortfolioUnavailableError`) - jamais un
    repli silencieux à 100% pour un exchange qui n'a jamais été
    explicitement configuré (mandat §11 : "Le système ne doit jamais
    pouvoir dépasser cette limite")."""
    # `market_type IS NULL` (17/08/2026) : convention "NULL = solde spot"
    # (même pattern que `decisions.market_type`) - un solde de marge
    # futures (`market_type='futures_perpetual'`) ne doit JAMAIS être
    # confondu avec le capital spot dimensionnant une décision spot.
    portfolio_row = await conn.fetchrow(
        """
        SELECT total_value_reference_currency, taken_at FROM portfolio_snapshots
        WHERE exchange = $1 AND market_type IS NULL
        ORDER BY taken_at DESC LIMIT 1;
        """,
        exchange,
    )
    if portfolio_row is None:
        raise PortfolioUnavailableError(
            f"Aucun instantané de portefeuille disponible pour l'exchange '{exchange}'."
        )

    snapshot_age_seconds = (datetime.now(tz=UTC) - portfolio_row["taken_at"]).total_seconds()
    if snapshot_age_seconds > PORTFOLIO_SNAPSHOT_MAX_AGE_SECONDS:
        raise PortfolioUnavailableError(
            f"Dernier instantané de portefeuille pour '{exchange}' trop ancien "
            f"({snapshot_age_seconds:.0f}s > {PORTFOLIO_SNAPSHOT_MAX_AGE_SECONDS}s)."
        )

    allocation_row = await conn.fetchrow(
        """
        SELECT allocation_pct FROM capital_allocation_config
        WHERE exchange = $1
        ORDER BY set_at DESC LIMIT 1;
        """,
        exchange,
    )
    if allocation_row is None:
        raise PortfolioUnavailableError(
            f"Aucune allocation de capital configurée pour '{exchange}' (capital_allocation_config) - "
            "le mur d'allocation exige un choix explicite avant toute exposition en mode réel."
        )

    total_capital = Decimal(str(portfolio_row["total_value_reference_currency"]))
    allocation_pct = Decimal(str(allocation_row["allocation_pct"]))
    return total_capital * allocation_pct / Decimal(100)


async def _build_risk_context(db_pool, redis_client, decision) -> RiskContext:
    exchange = decision["exchange"]
    symbol = decision["symbol"]

    async with db_pool.acquire() as conn:
        # Mode d'exécution courant (ADR-0004/0008) - lu depuis
        # execution_mode_state, plus jamais depuis une variable
        # d'environnement figée au démarrage du conteneur.
        current_execution_mode = await fetch_current_mode(conn)

        latest_candle = await conn.fetchrow(
            """
            SELECT close FROM ohlcv_candles_1m
            WHERE exchange = $1 AND symbol = $2
            ORDER BY bucket DESC LIMIT 1;
            """,
            exchange,
            symbol,
        )
        current_price = Decimal(str(latest_candle["close"])) if latest_candle else Decimal("0")

        order_book_row = await conn.fetchrow(
            """
            SELECT bids, asks FROM order_book_snapshots
            WHERE exchange = $1 AND symbol = $2
            ORDER BY time DESC LIMIT 1;
            """,
            exchange,
            symbol,
        )
        bids = _parse_book_levels(order_book_row["bids"]) if order_book_row else []
        asks = _parse_book_levels(order_book_row["asks"]) if order_book_row else []

        open_positions = await conn.fetch(
            "SELECT entry_price, quantity FROM positions WHERE status = 'open' AND execution_mode = $1;",
            current_execution_mode,
        )
        current_exposure = sum(
            (Decimal(str(p["entry_price"])) * Decimal(str(p["quantity"])) for p in open_positions),
            Decimal("0"),
        )

        own_open_spot_position = await conn.fetchrow(
            """
            SELECT quantity FROM positions
            WHERE status = 'open' AND execution_mode = $1 AND exchange = $2 AND symbol = $3
                  AND market_type = 'spot';
            """,
            current_execution_mode,
            exchange,
            symbol,
        )
        existing_spot_quantity = (
            Decimal(str(own_open_spot_position["quantity"])) if own_open_spot_position else Decimal("0")
        )

        own_open_futures_position = await conn.fetchrow(
            """
            SELECT quantity FROM positions
            WHERE status = 'open' AND execution_mode = $1 AND exchange = $2 AND symbol = $3
                  AND market_type = 'futures_perpetual';
            """,
            current_execution_mode,
            exchange,
            symbol,
        )
        existing_futures_quantity = (
            Decimal(str(own_open_futures_position["quantity"])) if own_open_futures_position else Decimal("0")
        )

        realized_pnl_row = await conn.fetchrow(
            """
            SELECT COALESCE(SUM(realized_pnl), 0) AS total
            FROM positions
            WHERE status = 'closed' AND execution_mode = $1 AND closed_at >= date_trunc('day', now());
            """,
            current_execution_mode,
        )
        daily_realized_pnl = Decimal(str(realized_pnl_row["total"]))

        recent_closed = await conn.fetch(
            """
            SELECT realized_pnl, closed_at FROM positions
            WHERE status = 'closed' AND execution_mode = $1
            ORDER BY closed_at DESC
            LIMIT $2;
            """,
            current_execution_mode,
            CONSECUTIVE_LOSS_LOOKBACK,
        )
        consecutive_losses = 0
        # Correctif du 19/08/2026 - cf. RiskContext.most_recent_loss_closed_at
        # pour le contexte complet du bug corrigé (blocage définitif
        # possible sans cette information).
        most_recent_loss_closed_at = None
        for position in recent_closed:
            if Decimal(str(position["realized_pnl"])) < 0:
                consecutive_losses += 1
                if most_recent_loss_closed_at is None:
                    most_recent_loss_closed_at = position["closed_at"]
            else:
                break

        # Chantier de routage par market_type (16/08/2026), déplacé ici
        # le 18/08/2026 (AVANT le capital disponible, pas après) :
        # nécessaire depuis la séparation du Paper Vault en deux pools
        # indépendants (spot/futures, cf. _fetch_paper_available_capital)
        # - le pool à consulter dépend directement de ce market_type, il
        # doit donc être connu avant, jamais après, l'appel qui suit.
        #
        # Si `decision_engine` a explicitement déclaré le market_type
        # (moteur `market_type="futures_perpetual"` dans son
        # `EngineMetadata`, ex. `liquidation_cascade`), cette valeur
        # prévaut - jamais recalculée via l'heuristique
        # `determine_market_type` (ADR-0019, conçue pour un problème plus
        # étroit : router un SELL sans position spot vers le futures).
        # `decision["market_type"]` reste NULL pour toute décision
        # produite par un moteur spot (comportement inchangé,
        # rétrocompatibilité totale) - l'heuristique historique continue
        # de s'appliquer exactement comme avant ce chantier.
        suggested_side = Side.BUY if decision["suggested_side"] == "buy" else Side.SELL
        if decision["market_type"] is not None:
            market_type = decision["market_type"]
            open_position_quantity = (
                existing_futures_quantity if market_type == "futures_perpetual" else existing_spot_quantity
            )
        else:
            market_type = determine_market_type(
                suggested_side, existing_spot_quantity, existing_futures_quantity
            )
            open_position_quantity = (
                existing_futures_quantity if market_type == "futures_perpetual" else existing_spot_quantity
            )

        # Capital disponible (Étapes 4/5, 16/08/2026 ; pools Paper
        # séparés par market_type depuis le 18/08/2026) - source
        # totalement différente selon le mode courant, jamais une seule
        # requête indifférenciée comme avant ce chantier (cf. docstring
        # des deux fonctions ci-dessus).
        if current_execution_mode == "paper":
            available_capital = await _fetch_paper_available_capital(conn, market_type)
        else:
            available_capital = await _fetch_real_available_capital(conn, exchange)

    kill_switch_raw = await redis_client.get(KILL_SWITCH_REDIS_KEY)
    kill_switch_active = kill_switch_raw is not None and kill_switch_raw == b"1"

    return RiskContext(
        decision_id=decision["id"],
        exchange=exchange,
        symbol=symbol,
        suggested_side=suggested_side,
        success_probability=decision["success_probability"],
        expected_value=decision["expected_value"],
        risk_reward_ratio=decision["risk_reward_ratio"],
        available_capital=available_capital,
        current_price=current_price,
        current_exposure_notional=current_exposure,
        daily_realized_pnl=daily_realized_pnl,
        consecutive_losses=consecutive_losses,
        most_recent_loss_closed_at=most_recent_loss_closed_at,
        order_book_bids=bids,
        order_book_asks=asks,
        kill_switch_active=kill_switch_active,
        market_type=market_type,
        open_position_quantity=open_position_quantity,
    )


def _parse_book_levels(raw_json: str) -> list[tuple[Decimal, Decimal]]:
    levels = json.loads(raw_json)
    return [(Decimal(str(price)), Decimal(str(qty))) for price, qty in levels]
