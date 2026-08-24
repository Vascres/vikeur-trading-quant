"""API Backend (Phase 2, §4.9 ; Phase 18 ; sécurisée en Module 1).

Principalement en lecture seule. Trois actions d'écriture exposées, toutes
des actes humains volontaires, jamais déclenchés automatiquement depuis
le dashboard : le kill switch (Phase 13, §4), le changement de mode
d'exécution (ADR-0004, ADR-0008 - gouverné, prérequis vérifiés
automatiquement pour le passage en mode réel), et les attestations de
gouvernance (kill switch testé, sauvegardes vérifiées, monitoring actif).
Aucune commande de trading n'est exposée par ailleurs.

Toutes les routes (sauf /health) exigent un jeton Bearer valide et sont
soumises à une limite de débit (Module 1, §4-5).
"""

import asyncio
import json
import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import asyncpg
import redis.asyncio as redis
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import execution_mode_governance.main as governance
from backtesting.metrics import calmar_ratio, max_drawdown, sharpe_ratio, sortino_ratio
from calibration.bayesian_provider import MINIMUM_SAMPLE_SIZE_PRELIMINARY, MINIMUM_SAMPLE_SIZE_VALIDATED
from shared.auth import enforce_rate_limit, verify_token
from shared.strategy_performance import build_daily_returns_and_equity_curve

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]
KILL_SWITCH_REDIS_KEY = "risk:kill_switch"
JOURNAL_CHANNEL = "events:journal"

db_pool: asyncpg.Pool | None = None
redis_client: redis.Redis | None = None


def _publish_journal_event(source_module: str) -> Callable[[str, dict], None]:
    """Fabrique un callable synchrone de publication (fire-and-forget via
    asyncio.create_task) - même pattern que tous les autres modules du
    backend (data_collector, decision_engine, risk_engine...). Nécessaire
    ici car execution_mode_governance.request_mode_change() appelle son
    paramètre `publish_journal_event` de façon synchrone, jamais via await."""

    def publish(event_type: str, payload: dict) -> None:
        asyncio.create_task(
            redis_client.publish(
                JOURNAL_CHANNEL,
                json.dumps(
                    {"source_module": source_module, "event_type": event_type, "payload": payload},
                    default=str,
                ),
            )
        )

    return publish


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool, redis_client
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    redis_client = redis.from_url(REDIS_URL)
    yield
    await db_pool.close()
    await redis_client.aclose()


async def _rate_limit(request: Request) -> None:
    await enforce_rate_limit(request, redis_client)


app = FastAPI(title="Plateforme Quant - API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        os.environ.get("PUBLIC_API_URL", "").replace("/api", "") or "http://localhost:3000",
        "http://localhost:3000",  # développement local uniquement
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Toutes les routes protégées passent par ce routeur (Module 1, §5) -
# /health reste public (sonde de disponibilité, aucune donnée sensible).
secured = APIRouter(dependencies=[Depends(verify_token), Depends(_rate_limit)])


class KillSwitchPayload(BaseModel):
    active: bool


class ExecutionModeChangePayload(BaseModel):
    target_mode: str
    requested_by: str
    confirmation_phrase: str | None = None


class GovernanceAttestationPayload(BaseModel):
    key: str
    attested_by: str
    notes: str | None = None


class CapitalAllocationPayload(BaseModel):
    exchange: str
    allocation_pct: float
    set_by: str


class PaperCapitalPayload(BaseModel):
    initial_capital: float
    set_by: str
    # Deux pools séparés depuis le 18/08/2026 (mandat : suivi P&L
    # indépendant spot/futures) - "spot" par défaut, rétrocompatible
    # avec tout appelant existant qui ne le fournirait pas encore.
    market_type: str = "spot"


@app.get("/health")
async def health():
    return {"status": "ok"}


@secured.get("/positions")
async def get_positions(execution_mode: str = "paper", status: str = "open", limit: int = 100):
    """Étendu (sans rien retirer) pour la traçabilité gains/pertes demandée :
    `decision_id` permet de relier chaque position à la décision qui l'a
    ouverte (`/decisions/{id}/explain`, déjà existant) ; `market_type`/
    `position_side` (ADR-0018/0019) distinguent spot et futures - aucun
    champ existant n'est modifié, uniquement des ajouts (ancien code
    frontend continue de fonctionner à l'identique)."""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, exchange, symbol, execution_mode, entry_price, exit_price,
                   quantity, realized_pnl, unrealized_pnl, status, opened_at, closed_at,
                   decision_id, market_type, position_side
            FROM positions
            WHERE execution_mode = $1 AND status = $2
            ORDER BY opened_at DESC
            LIMIT $3;
            """,
            execution_mode,
            status,
            limit,
        )
    return [dict(r) for r in rows]


@secured.get("/portfolio/summary")
async def get_portfolio_summary(execution_mode: str = "paper"):
    """Fonds réels de l'exchange (dernier relevé connu, `portfolio_snapshots`)
    et bilan gains/pertes (`positions`) - toutes les données existaient déjà
    en base, cet endpoint ne fait que les agréger pour un affichage dédié
    du dashboard, sans toucher aux endpoints existants.

    Correctif du 17/08/2026 (solde de marge futures) : `DISTINCT ON
    (exchange, market_type)` plutôt que `DISTINCT ON (exchange)` seul -
    un exchange peut désormais avoir DEUX instantanés les plus récents
    (spot et futures), jamais l'un écrasant silencieusement l'autre. Le
    frontend distingue les deux via le champ `market_type` renvoyé
    (`NULL` = spot, `'futures_perpetual'` = marge futures)."""
    async with db_pool.acquire() as conn:
        balances = await conn.fetch(
            """
            SELECT DISTINCT ON (exchange, market_type) exchange, total_value_reference_currency,
                   reference_currency, taken_at, market_type
            FROM portfolio_snapshots
            ORDER BY exchange, market_type, taken_at DESC;
            """
        )
        stats = await conn.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'closed') AS closed_trades,
                COUNT(*) FILTER (WHERE status = 'open') AS open_trades,
                COALESCE(SUM(realized_pnl) FILTER (WHERE status = 'closed'), 0) AS total_realized_pnl,
                COUNT(*) FILTER (WHERE status = 'closed' AND realized_pnl > 0) AS winning_trades,
                COUNT(*) FILTER (WHERE status = 'closed' AND realized_pnl <= 0) AS losing_trades
            FROM positions
            WHERE execution_mode = $1;
            """,
            execution_mode,
        )

    return {
        "balances": [dict(b) for b in balances],
        "closed_trades": stats["closed_trades"],
        "open_trades": stats["open_trades"],
        "total_realized_pnl": stats["total_realized_pnl"],
        "winning_trades": stats["winning_trades"],
        "losing_trades": stats["losing_trades"],
    }


# --- Étape 5 (16/08/2026) : mur d'allocation du capital réel ---


@secured.get("/capital-allocation")
async def get_capital_allocation():
    """Dernière allocation connue par exchange (`capital_allocation_config`) -
    consommé par `risk_engine` en SQL direct (jamais via cet endpoint),
    exposé ici uniquement pour le dashboard et la configuration humaine."""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (exchange) exchange, allocation_pct, set_at, set_by
            FROM capital_allocation_config
            ORDER BY exchange, set_at DESC;
            """
        )
    return [dict(r) for r in rows]


@secured.post("/capital-allocation")
async def set_capital_allocation(payload: CapitalAllocationPayload):
    """Pose une nouvelle allocation (jamais une mutation de l'existante -
    historique complet conservé, même principe que execution_mode_state).
    Le mandat §11 est explicite : "Le système ne doit jamais pouvoir
    dépasser cette limite" - validée ici avant toute écriture, puis
    appliquée réellement par risk_engine à chaque décision (jamais
    seulement affichée côté frontend)."""
    if not (0 < payload.allocation_pct <= 100):
        raise HTTPException(status_code=400, detail="allocation_pct doit être dans ]0, 100].")

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO capital_allocation_config (exchange, allocation_pct, set_by)
            VALUES ($1, $2, $3);
            """,
            payload.exchange,
            payload.allocation_pct,
            payload.set_by,
        )
    _publish_journal_event("api")(
        "capital_allocation.changed",
        {"exchange": payload.exchange, "allocation_pct": payload.allocation_pct, "set_by": payload.set_by},
    )
    return {"exchange": payload.exchange, "allocation_pct": payload.allocation_pct}


# --- Étape 4 (16/08/2026) : capital virtuel du Paper Portfolio ---


@secured.get("/paper-capital")
async def get_paper_capital(market_type: str = "spot"):
    """Capital paper courant - même calcul que `risk_engine._fetch_paper_available_capital`
    (capital initial le plus récent + P&L réalisé simulé depuis lors),
    dupliqué ici en lecture seule pour l'affichage (aucune décision n'est
    prise par cet endpoint, jamais un chemin détourné vers le risque -
    même principe que les autres services isolés du flux live).

    Deux pools séparés depuis le 18/08/2026 (`market_type='spot'` ou
    `'futures_perpetual'`) - convention NULL=spot en base, identique à
    `risk_engine._fetch_paper_available_capital` (même chantier, jamais
    deux logiques différentes pour la même donnée)."""
    if market_type not in ("spot", "futures_perpetual"):
        raise HTTPException(status_code=400, detail="market_type doit être 'spot' ou 'futures_perpetual'.")

    async with db_pool.acquire() as conn:
        config_row = await conn.fetchrow(
            "SELECT initial_capital, reference_currency, set_at, set_by "
            "FROM paper_capital_config WHERE market_type IS NOT DISTINCT FROM $1 "
            "ORDER BY set_at DESC LIMIT 1;",
            market_type if market_type == "futures_perpetual" else None,
        )
        if config_row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Aucune configuration de capital Paper trouvée pour le marché '{market_type}'.",
            )

        pnl_row = await conn.fetchrow(
            """
            SELECT COALESCE(SUM(realized_pnl), 0) AS total FROM positions
            WHERE execution_mode = 'paper' AND status = 'closed' AND market_type = $1 AND closed_at > $2;
            """,
            market_type,
            config_row["set_at"],
        )

    current_capital = config_row["initial_capital"] + pnl_row["total"]
    return {
        "initial_capital": config_row["initial_capital"],
        "current_capital": current_capital,
        "reference_currency": config_row["reference_currency"],
        "set_at": config_row["set_at"],
        "set_by": config_row["set_by"],
        "market_type": market_type,
    }


@secured.post("/paper-capital")
async def set_paper_capital(payload: PaperCapitalPayload):
    """Réinitialise le capital de référence du Paper Portfolio (jamais une
    mutation de l'existante, même principe que capital-allocation) -
    l'historique des trades déjà simulés n'est jamais effacé (Règle
    Absolue du mandat), seul le point de départ du calcul de capital
    courant change à partir de maintenant.

    Deux pools séparés depuis le 18/08/2026 - `payload.market_type`
    détermine lequel des deux est réinitialisé, jamais les deux à la
    fois (poser 350 USDT en spot ne touche jamais au pool futures, et
    inversement)."""
    if payload.initial_capital <= 0:
        raise HTTPException(status_code=400, detail="initial_capital doit être strictement positif.")
    if payload.market_type not in ("spot", "futures_perpetual"):
        raise HTTPException(status_code=400, detail="market_type doit être 'spot' ou 'futures_perpetual'.")

    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO paper_capital_config (initial_capital, set_by, market_type) VALUES ($1, $2, $3);",
            payload.initial_capital,
            payload.set_by,
            payload.market_type if payload.market_type == "futures_perpetual" else None,
        )
    _publish_journal_event("api")(
        "paper_capital.reset",
        {
            "initial_capital": payload.initial_capital,
            "set_by": payload.set_by,
            "market_type": payload.market_type,
        },
    )
    return {"initial_capital": payload.initial_capital, "market_type": payload.market_type}


@secured.get("/decisions")
async def get_decisions(limit: int = Query(default=50, le=500)):
    """LEFT JOIN (ADR-0010) : une décision issue d'une fusion multi-moteurs
    n'a plus de `strategy_id` (`meta_decision_id` à la place) - un INNER
    JOIN l'exclurait silencieusement du dashboard.

    Colonnes `md.*` ajoutées (ADR-0014, ADR-0015, Decision Explainability) :
    la liste de décisions ne doit plus se limiter à un `verdict` opaque
    (ex. `no_signal` sans contexte) - `calibration_maturity`,
    `verdict_reason`, `execution_mode` et `regime_type` permettent au
    dashboard d'afficher un résumé immédiatement lisible, sans imposer un
    aller-retour vers `/decisions/{id}/explain` pour chaque ligne."""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT d.id, d.exchange, d.symbol, d.time, d.success_probability,
                   d.expected_value, d.risk_reward_ratio, d.verdict, d.suggested_side,
                   COALESCE(s.name, 'fusion_multi_moteurs') AS strategy_name,
                   d.meta_decision_id,
                   md.calibration_maturity, md.verdict_reason, md.execution_mode,
                   md.regime_type, md.fused_score
            FROM decisions d
            LEFT JOIN strategies s ON s.id = d.strategy_id
            LEFT JOIN meta_decisions md ON md.id = d.meta_decision_id
            ORDER BY d.time DESC
            LIMIT $1;
            """,
            limit,
        )
    return [dict(r) for r in rows]


@secured.get("/logs")
async def get_logs(limit: int = Query(default=100, le=1000), source_module: str | None = None):
    async with db_pool.acquire() as conn:
        if source_module:
            rows = await conn.fetch(
                """
                SELECT id, source_module, event_type, payload, time FROM events_journal
                WHERE source_module = $1 ORDER BY time DESC LIMIT $2;
                """,
                source_module,
                limit,
            )
        else:
            rows = await conn.fetch(
                "SELECT id, source_module, event_type, payload, time FROM events_journal ORDER BY time DESC LIMIT $1;",
                limit,
            )
    return [dict(r) for r in rows]


@secured.get("/strategies/performance")
async def get_strategies_performance():
    """Réutilise les recommandations déjà calculées par la Phase 17 - ne recalcule rien ici."""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.name, s.is_active, sa.recommended_fraction, sa.based_on_trade_count, sa.computed_at
            FROM strategies s
            LEFT JOIN LATERAL (
                SELECT * FROM strategy_allocations
                WHERE strategy_id = s.id
                ORDER BY computed_at DESC
                LIMIT 1
            ) sa ON true
            ORDER BY s.name;
            """
        )
    return [dict(r) for r in rows]


@secured.get("/strategies/lifecycle")
async def get_strategies_lifecycle():
    """Statut de Strategy Lifecycle (Étape 3, 16/08/2026) - distinct de
    `/strategies/performance` ci-dessus (recommandation d'allocation,
    Phase 17, jamais mise à jour automatiquement) : ce statut est le
    seul qui détermine réellement si une stratégie contribue à la
    fusion (`decision_engine.thresholds.is_excluded_from_fusion`).

    `LEFT JOIN` plutôt qu'un `JOIN` strict : une stratégie active sans
    encore de ligne `strategy_lifecycle_state` (cas impossible en
    pratique une fois `strategy_lifecycle` déployé, qui l'initialise
    automatiquement - mais jamais supposé côté API) apparaît quand même,
    avec `status: null`, plutôt que d'être silencieusement omise."""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.id AS strategy_id, s.name, sl.status, sl.reason, sl.ev_net_bps,
                   sl.cumulative_pnl_reference_currency, sl.profit_factor,
                   sl.sample_size, sl.transitioned_at
            FROM strategies s
            LEFT JOIN strategy_lifecycle_state sl ON sl.strategy_id = s.id
            WHERE s.is_active = TRUE
            ORDER BY s.name;
            """
        )
    return [dict(r) for r in rows]


@secured.get("/strategies/{strategy_id}/performance-metrics")
async def get_strategy_performance_metrics(
    strategy_id: int, execution_mode: str = Query(default="paper"), limit: int = Query(default=200, le=1000)
):
    """Sharpe/Sortino/Calmar/Max Drawdown par stratégie (mandat §14,
    chantier Strategy Dashboard du 16/08/2026) - réutilise les fonctions
    pures déjà écrites et testées de `backtesting/metrics.py` (Phase 14),
    jamais réimplémentées ici.

    Attribution des trades : même jointure double (chemin direct
    `decisions.strategy_id` + chemin fusionné `decisions.
    meta_decision_id -> meta_decisions.contributing_opinion_ids ->
    engine_opinions.strategy_id`) que `strategy_lifecycle/repository.py`
    - dupliquée plutôt qu'importée (`strategy_lifecycle` reste un
    service de mesure isolé, contrat import-linter 13, jamais un import
    croisé), avec cette fois un filtre `execution_mode` explicite (le
    Sharpe d'un compte paper et d'un compte réel n'ont pas de raison
    d'être mélangés, contrairement au calcul d'éviction de l'Étape 3 qui
    ne distinguait pas les deux - limitation distincte, pas reproduite
    ici).

    Rendements regroupés par JOUR de clôture (`shared.
    strategy_performance.build_daily_returns_and_equity_curve`), jamais
    un rendement par trade utilisé tel quel - `backtesting/metrics.py`
    annualise en supposant des rendements quotidiens (`sqrt(365)`),
    utiliser un rendement par trade produirait un facteur
    d'annualisation faux dès que la fréquence de trading n'est pas
    exactement d'un trade par jour."""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT realized_pnl, closed_at FROM (
                SELECT p.id, p.realized_pnl, p.closed_at
                FROM positions p
                JOIN decisions d ON d.id = p.decision_id
                WHERE d.strategy_id = $1 AND p.execution_mode = $2
                      AND p.status = 'closed' AND p.realized_pnl IS NOT NULL

                UNION

                SELECT p.id, p.realized_pnl, p.closed_at
                FROM positions p
                JOIN decisions d ON d.id = p.decision_id
                JOIN meta_decisions md ON md.id = d.meta_decision_id
                JOIN engine_opinions eo ON eo.id = ANY(md.contributing_opinion_ids)
                WHERE eo.strategy_id = $1 AND p.execution_mode = $2
                      AND p.status = 'closed' AND p.realized_pnl IS NOT NULL
            ) combined
            ORDER BY closed_at ASC
            LIMIT $3;
            """,
            strategy_id,
            execution_mode,
            limit,
        )

    trade_pnls_by_close_date = [(row["closed_at"].date(), float(row["realized_pnl"])) for row in rows]
    returns, equity_curve = build_daily_returns_and_equity_curve(trade_pnls_by_close_date)
    mdd = max_drawdown(equity_curve)

    return {
        "strategy_id": strategy_id,
        "execution_mode": execution_mode,
        "trade_count": len(rows),
        "days_observed": len(returns),
        "sharpe_ratio": sharpe_ratio(returns),
        "sortino_ratio": sortino_ratio(returns),
        "calmar_ratio": calmar_ratio(equity_curve),
        "max_drawdown_pct": mdd * 100 if mdd is not None else None,
    }


@secured.get("/why-no-trade")
async def get_why_no_trade(
    execution_mode: str = Query(default="paper"), since_hours: int = Query(default=24, le=168)
):
    """Entonnoir d'explicabilité (mandat §21, "Why No Trade ?") -
    reconstruit les points de filtrage RÉELS du pipeline fusionné actuel
    (les 3 moteurs directionnels actifs, `decision_engine`) à partir de
    ce qui est effectivement mesuré aujourd'hui (`engine_opinions`,
    `events_journal`, `decisions`, `risk_checks`, `orders`) - jamais une
    approximation ni un étage inventé.

    Portée délibérément limitée au pipeline fusionné : `pair_execution`
    (funding/basis) a son propre flux de décision, distinct
    (`strategy_id` direct, jamais de `meta_decision_id`), déjà exposé
    séparément (`/pair-decisions`) - le mélanger ici masquerait plus
    qu'il n'éclaircirait.

    Étage volontairement ABSENT : le CostModel. `cost_estimates.
    cleared_costs` reste purement observationnel (ADR-0016 §4, confirmé
    par l'audit du 16/08/2026 - "jamais utilisée pour bloquer une
    décision ici, seulement pour observer") : le représenter comme un
    étage qui "rejette" des décisions serait un mensonge visuel. Sa
    valeur informative est exposée séparément (`cost_model_note`).

    Dépend du correctif du 16/08/2026 (`journal/main.py`, second
    consommateur de `events:journal`) - avant ce correctif,
    `events_journal` était systématiquement vide et les étages
    "régime"/"aucun avis"/"lifecycle" auraient été silencieusement à
    zéro plutôt que reflétés honnêtement comme indisponibles."""
    since = datetime.now(tz=UTC) - timedelta(hours=since_hours)

    async with db_pool.acquire() as conn:
        opinions_generated = await conn.fetchval(
            "SELECT COUNT(*) FROM engine_opinions WHERE time >= $1;", since
        )
        skipped_regime = await conn.fetchval(
            """
            SELECT COUNT(*) FROM events_journal
            WHERE event_type = 'decision_engine.engine_skipped_regime' AND time >= $1;
            """,
            since,
        )
        no_opinion = await conn.fetchval(
            """
            SELECT COUNT(*) FROM events_journal
            WHERE event_type = 'decision_engine.no_opinion' AND time >= $1;
            """,
            since,
        )
        excluded_lifecycle = await conn.fetchval(
            """
            SELECT COUNT(*) FROM events_journal
            WHERE event_type = 'decision_engine.engine_excluded_from_fusion_lifecycle_status' AND time >= $1;
            """,
            since,
        )
        decisions_row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE d.verdict = 'no_signal') AS rejected_conviction,
                COUNT(*) FILTER (WHERE d.verdict = 'signal') AS passed_to_risk_engine,
                COUNT(*) AS total_decisions
            FROM decisions d
            JOIN meta_decisions md ON md.id = d.meta_decision_id
            WHERE d.time >= $1 AND md.execution_mode = $2;
            """,
            since,
            execution_mode,
        )
        risk_row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE rc.passed = FALSE) AS rejected_by_risk_engine,
                COUNT(*) FILTER (WHERE rc.passed = TRUE) AS accepted_by_risk_engine
            FROM risk_checks rc
            JOIN decisions d ON d.id = rc.decision_id
            JOIN meta_decisions md ON md.id = d.meta_decision_id
            WHERE rc.rule_name = 'FINAL_VERDICT' AND d.time >= $1 AND md.execution_mode = $2;
            """,
            since,
            execution_mode,
        )
        orders_executed = await conn.fetchval(
            "SELECT COUNT(*) FROM orders WHERE status = 'filled' AND execution_mode = $1 AND created_at >= $2;",
            execution_mode,
            since,
        )
        cost_model_row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE ce.cleared_costs = TRUE) AS cleared,
                COUNT(*) AS total
            FROM cost_estimates ce
            JOIN decisions d ON d.id = ce.decision_id
            JOIN meta_decisions md ON md.id = d.meta_decision_id
            WHERE d.time >= $1 AND md.execution_mode = $2;
            """,
            since,
            execution_mode,
        )

    return {
        "since": since.isoformat(),
        "execution_mode": execution_mode,
        "funnel": [
            {"stage": "opinions_generated", "label": "Avis moteur générés", "count": opinions_generated},
            {
                "stage": "skipped_regime",
                "label": "Écartés — régime de marché non autorisé",
                "count": skipped_regime,
            },
            {"stage": "no_opinion", "label": "Écartés — aucun avis produit", "count": no_opinion},
            {
                "stage": "excluded_lifecycle",
                "label": "Écartés — statut de cycle de vie",
                "count": excluded_lifecycle,
            },
            {
                "stage": "decisions_fused",
                "label": "Décisions fusionnées",
                "count": decisions_row["total_decisions"],
            },
            {
                "stage": "rejected_conviction",
                "label": "Rejetées — seuil de conviction non atteint",
                "count": decisions_row["rejected_conviction"],
            },
            {
                "stage": "passed_to_risk_engine",
                "label": "Transmises au Risk Engine",
                "count": decisions_row["passed_to_risk_engine"],
            },
            {
                "stage": "rejected_risk_engine",
                "label": "Refusées par le Risk Engine",
                "count": risk_row["rejected_by_risk_engine"] or 0,
            },
            {"stage": "orders_executed", "label": "Ordres exécutés", "count": orders_executed},
        ],
        "cost_model_note": {
            "cleared": cost_model_row["cleared"] or 0,
            "total": cost_model_row["total"] or 0,
            "note": (
                "Observationnel uniquement (ADR-0016 §4) - ne bloque encore aucune "
                "décision, jamais un étage de l'entonnoir."
            ),
        },
    }


@secured.get("/kill-switch")
async def get_kill_switch():
    value = await redis_client.get(KILL_SWITCH_REDIS_KEY)
    return {"active": value == b"1"}


@secured.post("/kill-switch")
async def set_kill_switch(payload: KillSwitchPayload):
    """Seule action d'écriture exposée par l'API (Phase 18, §3) - un acte
    humain volontaire, jamais déclenché automatiquement depuis le dashboard.

    Correctif du 16/08/2026 (chantier Telegram) : cette action ne
    publiait jusqu'ici aucun événement journalisé - l'action de sécurité
    la plus critique du système (mandat §18 : "🛑 KILL SWITCH ACTIVATED")
    était donc invisible pour tout consommateur du canal `events:journal`,
    y compris le futur service de notifications."""
    await redis_client.set(KILL_SWITCH_REDIS_KEY, "1" if payload.active else "0")
    _publish_journal_event("api")(
        "kill_switch.activated" if payload.active else "kill_switch.deactivated",
        {"active": payload.active},
    )
    return {"active": payload.active}


@secured.get("/execution-mode")
async def get_execution_mode_status():
    """État courant, historique récent, et statut des prérequis pour le
    passage en mode réel (ADR-0004, ADR-0008) - consommé par le dashboard."""
    return await governance.get_status(db_pool, redis_client)


@secured.post("/execution-mode")
async def change_execution_mode(payload: ExecutionModeChangePayload):
    """Point d'entrée unique pour tout changement de mode (Architecture
    Cible V2, §5.2) - toute la logique de gouvernance vit dans
    execution_mode_governance, cette route ne fait qu'exposer le contrat."""
    result = await governance.request_mode_change(
        db_pool,
        redis_client,
        payload.target_mode,
        payload.requested_by,
        payload.confirmation_phrase,
        _publish_journal_event("execution_mode_governance"),
    )
    if not result.accepted:
        raise HTTPException(status_code=400, detail=result.reason)
    return {
        "accepted": True,
        "new_mode": result.new_mode,
        "reason": result.reason,
    }


@secured.post("/execution-mode/attestations")
async def record_governance_attestation(payload: GovernanceAttestationPayload):
    """Enregistre une attestation humaine (kill switch testé, sauvegardes
    vérifiées, monitoring actif - cf. execution_mode_governance.checks.
    recent_attestation) - limitation assumée et documentée en ADR-0008 :
    pas de détection automatique fiable pour ces trois prérequis."""
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO governance_attestations (key, attested_by, notes) VALUES ($1, $2, $3);",
            payload.key,
            payload.attested_by,
            payload.notes,
        )
    return {"recorded": True, "key": payload.key}


@secured.get("/calibration")
async def get_calibration_status():
    """Dernière calibration active (validée) et la plus récente tentative,
    même si non validée - visibilité minimale pour le dashboard (ADR-0009).
    Aucune écriture ici : le cycle de calibration tourne dans son propre
    service (`calibration`), jamais déclenché depuis l'API."""
    async with db_pool.acquire() as conn:
        active = await conn.fetchrow(
            "SELECT * FROM calibration_runs WHERE is_active ORDER BY computed_at DESC LIMIT 1;"
        )
        latest_attempt = await conn.fetchrow(
            "SELECT * FROM calibration_runs ORDER BY computed_at DESC LIMIT 1;"
        )
    return {
        "active_calibration": dict(active) if active else None,
        "latest_attempt": dict(latest_attempt) if latest_attempt else None,
    }


@secured.get("/decisions/{decision_id}/explain")
async def explain_decision(decision_id: int):
    """Decision Explainability (ADR-0014, ADR-0015) : pour une décision
    issue d'une fusion, retourne l'intégralité de la chaîne de preuve -
    chaque `EngineOpinion` contributeur (score, confiance, justification),
    la `MetaDecision` (fusion, calibration appliquée, niveau de maturité
    Confidence Lifecycle, régime de marché détecté, raison du verdict en
    langage humain), et les `risk_checks` associés (motif exact d'un
    éventuel rejet côté Risk Engine) - aucune décision ne doit rester une
    simple étiquette 'no_signal' sans justification (principe directeur 1).
    """
    async with db_pool.acquire() as conn:
        decision = await conn.fetchrow("SELECT * FROM decisions WHERE id = $1;", decision_id)
        if decision is None:
            raise HTTPException(status_code=404, detail="Décision introuvable.")

        risk_checks = await conn.fetch(
            "SELECT rule_name, passed, reason, time FROM risk_checks "
            "WHERE decision_id = $1 ORDER BY time ASC;",
            decision_id,
        )

        if decision["meta_decision_id"] is None:
            trades_observed = await conn.fetchval(
                "SELECT count(*) FROM positions WHERE status = 'closed' AND decision_id IS NOT NULL;"
            )
            return {
                "decision": dict(decision),
                "meta_decision": None,
                "contributing_opinions": [],
                "risk_checks": [dict(r) for r in risk_checks],
                "calibration": None,
                "calibration_progress": {
                    "trades_observed": trades_observed,
                    "minimum_for_preliminary": MINIMUM_SAMPLE_SIZE_PRELIMINARY,
                    "minimum_for_validated": MINIMUM_SAMPLE_SIZE_VALIDATED,
                },
            }

        meta_decision_row = await conn.fetchrow(
            "SELECT * FROM meta_decisions WHERE id = $1;", decision["meta_decision_id"]
        )
        meta_decision = dict(meta_decision_row)
        # asyncpg ne décode jamais automatiquement une colonne JSONB (elle
        # revient sous forme de texte JSON brut) - déjà géré ainsi partout
        # ailleurs dans le backend (cf. meta_engine/calibration_lookup.py
        # pour `calibration_runs.parameters`) ; oublié ici lors de l'ajout
        # de cet endpoint, corrigé pour que `weights_applied` soit un objet
        # exploitable côté frontend plutôt qu'une chaîne de caractères.
        if isinstance(meta_decision.get("weights_applied"), str):
            meta_decision["weights_applied"] = json.loads(meta_decision["weights_applied"])

        opinions = await conn.fetch(
            """
            SELECT eo.*, s.name AS engine_name FROM engine_opinions eo
            JOIN strategies s ON s.id = eo.strategy_id
            WHERE eo.id = ANY($1::bigint[]);
            """,
            meta_decision["contributing_opinion_ids"],
        )
        opinions_list = []
        for o in opinions:
            opinion = dict(o)
            if isinstance(opinion.get("rationale"), str):
                opinion["rationale"] = json.loads(opinion["rationale"])
            opinions_list.append(opinion)

        calibration = None
        if meta_decision["calibration_run_id"] is not None:
            calibration = await conn.fetchrow(
                "SELECT method, sample_size, is_validated, brier_score, computed_at, reason "
                "FROM calibration_runs WHERE id = $1;",
                meta_decision["calibration_run_id"],
            )

        # Retour d'expérience du dashboard (ADR-0014/0015, feedback UX) :
        # afficher "0.0%" quand aucune probabilité calibrée n'existe est
        # trompeur - un utilisateur le lit comme une vraie probabilité
        # nulle, pas comme "indisponible". `trades_observed` permet au
        # frontend d'afficher "X / 30 trades" à la place, cohérent avec
        # la même requête que `calibration/main.py::_gather_historical_data`
        # (positions clôturées avec decision_id renseigné).
        trades_observed = await conn.fetchval(
            "SELECT count(*) FROM positions WHERE status = 'closed' AND decision_id IS NOT NULL;"
        )

    return {
        "decision": dict(decision),
        "meta_decision": meta_decision,
        "contributing_opinions": opinions_list,
        "risk_checks": [dict(r) for r in risk_checks],
        "calibration": dict(calibration) if calibration else None,
        "calibration_progress": {
            "trades_observed": trades_observed,
            "minimum_for_preliminary": MINIMUM_SAMPLE_SIZE_PRELIMINARY,
            "minimum_for_validated": MINIMUM_SAMPLE_SIZE_VALIDATED,
        },
    }


@secured.get("/pair-decisions")
async def get_pair_decisions(limit: int = 50):
    """Historique des évaluations du Pair Execution Engine (ADR-0021) -
    accept ET reject, chaque évaluation est persistée depuis le
    correctif du 16/08/2026 (un rejet n'était auparavant jamais visible
    après coup)."""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, exchange, symbol, funding_rate_bps, gross_edge_bps, fees_bps, slippage_bps,
                   net_edge_bps, execution_probability, execution_risk, pair_quality_score,
                   decision, status, created_at, resolved_at
            FROM pair_decisions
            ORDER BY created_at DESC
            LIMIT $1;
            """,
            limit,
        )
    return [dict(r) for r in rows]


@secured.get("/pair-incidents")
async def get_pair_incidents(limit: int = 50):
    """Incidents d'exécution partielle (ADR-0021 §4.5) - une seule jambe
    remplie, avec le coût réel mesuré de la résolution une fois connu."""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, pair_decision_id, incident_type, filled_leg, missing_leg,
                   residual_exposure_notional, resolution_action, realized_cost_bps,
                   detected_at, resolved_at
            FROM pair_incidents
            ORDER BY detected_at DESC
            LIMIT $1;
            """,
            limit,
        )
    return [dict(r) for r in rows]


@secured.get("/liquidation-cascade/recent")
async def get_liquidation_cascade_recent(limit: int = 50):
    """Avis récents du moteur `liquidation_cascade` (chantier du
    16/08/2026, câblé au routage par market_type le même soir) - remplace
    la carte Pair Execution Engine sur le tableau de bord (17/08/2026,
    demande frontend) : `pair_execution` reste hors fusion et documenté
    comme sans mécanisme de sortie (audit initial), `liquidation_cascade`
    est le moteur futures réellement actif aujourd'hui.

    Un avis présent ici signifie que les deux seuils (intensité de
    liquidation ET mouvement de prix, `strategies/liquidation_cascade.py`)
    ont déjà été franchis - un cycle sous le seuil ne produit jamais de
    ligne `engine_opinions` (`evaluate()` retourne `None`, cf. sa
    docstring), donc rien à afficher ici pour ce cycle plutôt qu'une ligne
    vide.

    Rationale extrait du JSONB (`liquidation_cascade_intensity`,
    `momentum`, `spread_bps`) - les seuils eux-mêmes restent des valeurs
    de départ, jamais calibrées empiriquement à ce jour (collecte tout
    juste démarrée, cf. README "Limitations connues")."""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT eo.id, eo.exchange, eo.symbol, eo.time, eo.suggested_side, eo.score, eo.confidence,
                   (eo.rationale->>'liquidation_cascade_intensity')::double precision AS liquidation_notional_usd,
                   (eo.rationale->>'momentum')::double precision AS momentum,
                   (eo.rationale->>'spread_bps')::double precision AS spread_bps
            FROM engine_opinions eo
            JOIN strategies s ON s.id = eo.strategy_id
            WHERE s.name = 'liquidation_cascade'
            ORDER BY eo.time DESC
            LIMIT $1;
            """,
            limit,
        )
    return [dict(r) for r in rows]


app.include_router(secured)
