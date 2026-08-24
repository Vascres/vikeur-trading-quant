"""Tests de risk_engine.main._build_risk_context / _evaluate_decision
après le remplacement de STARTING_CAPITAL par le portefeuille réel
(ADR-0003, ADR-0007).

Aucun test existant ne couvrait ces deux fonctions avant ce chantier
(seules les RiskRule individuelles étaient testées en isolation, cf.
test_risk_engine.py) - ces tests comblent ce manque en plus de vérifier
le nouveau comportement, conformément à Development Standards §7 (ne
jamais faire baisser la couverture globale).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from risk_engine.main import (
    PortfolioUnavailableError,
    _build_risk_context,
    _evaluate_decision,
)


def _make_pool(fetchrow_by_key: dict[str, dict | None], fetch_by_key: dict[str, list] | None = None):
    fetch_by_key = fetch_by_key or {}

    async def fetchrow_side_effect(query, *args):
        for key, value in fetchrow_by_key.items():
            if key in query:
                return value
        raise AssertionError(f"Requête fetchrow non attendue par le test : {query}")

    async def fetch_side_effect(query, *args):
        for key, value in fetch_by_key.items():
            if key in query:
                return value
        raise AssertionError(f"Requête fetch non attendue par le test : {query}")

    conn = AsyncMock()
    conn.fetchrow.side_effect = fetchrow_side_effect
    conn.fetch.side_effect = fetch_side_effect
    conn.fetchval = AsyncMock(return_value=42)
    conn.execute = AsyncMock()

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


def _decision(**overrides) -> dict:
    base = dict(
        id=1,
        exchange="htx",
        symbol="BTC/USDT",
        success_probability=0.6,
        expected_value=0.01,
        risk_reward_ratio=2.0,
        suggested_side="buy",
        # Chantier de routage par market_type (16/08/2026) : NULL par
        # défaut, comme toute décision produite par un moteur spot
        # aujourd'hui - `_build_risk_context` retombe alors sur
        # `determine_market_type` (ADR-0019), exactement comme avant ce
        # chantier. Les tests dédiés au routage explicite le surchargent.
        market_type=None,
    )
    base.update(overrides)
    return base


# Requêtes communes à tous les tests, indépendantes du capital - mode
# 'real' par défaut (Étapes 4/5, 16/08/2026) : ces tests valident le
# chemin de capital réel (portfolio_snapshots x allocation_pct) ; le
# chemin paper (paper_capital_config, totalement indépendant) est
# couvert séparément plus bas, précisément parce que les deux sources
# ne sont plus jamais confondues (c'est le bug corrigé par ce chantier -
# avant, le mode paper lisait aussi portfolio_snapshots).
_COMMON_FETCHROW = {
    "execution_mode_state": {"mode": "real"},
    "ohlcv_candles_1m": {"close": Decimal("60000")},
    "order_book_snapshots": None,
    "AND exchange = $2 AND symbol = $3": None,  # own_open_position
    "date_trunc('day'": {"total": Decimal("0")},  # daily_realized_pnl (distinct du P&L paper ci-dessous)
    "capital_allocation_config": {"allocation_pct": Decimal("100.00")},  # 100% = comportement historique
}
_COMMON_FETCH: dict[str, list] = {
    "entry_price, quantity FROM positions": [],  # open_positions
    "ORDER BY closed_at DESC": [],  # recent_closed
}


@pytest.mark.asyncio
async def test_build_risk_context_reads_capital_from_portfolio_snapshot():
    fresh_snapshot = {
        "total_value_reference_currency": Decimal("2500.50"),
        "taken_at": datetime.now(tz=UTC),
    }
    pool, _ = _make_pool(
        fetchrow_by_key={**_COMMON_FETCHROW, "portfolio_snapshots": fresh_snapshot},
        fetch_by_key=_COMMON_FETCH,
    )
    redis_client = AsyncMock()
    redis_client.get.return_value = None

    context = await _build_risk_context(pool, redis_client, _decision())

    assert context.available_capital == Decimal("2500.50")


@pytest.mark.asyncio
async def test_build_risk_context_blocks_when_no_snapshot_exists():
    pool, _ = _make_pool(
        fetchrow_by_key={**_COMMON_FETCHROW, "portfolio_snapshots": None},
        fetch_by_key=_COMMON_FETCH,
    )
    redis_client = AsyncMock()
    redis_client.get.return_value = None

    with pytest.raises(PortfolioUnavailableError):
        await _build_risk_context(pool, redis_client, _decision())


@pytest.mark.asyncio
async def test_build_risk_context_blocks_when_snapshot_too_old():
    stale_snapshot = {
        "total_value_reference_currency": Decimal("2500"),
        "taken_at": datetime.now(tz=UTC) - timedelta(seconds=10_000),
    }
    pool, _ = _make_pool(
        fetchrow_by_key={**_COMMON_FETCHROW, "portfolio_snapshots": stale_snapshot},
        fetch_by_key=_COMMON_FETCH,
    )
    redis_client = AsyncMock()
    redis_client.get.return_value = None

    with pytest.raises(PortfolioUnavailableError):
        await _build_risk_context(pool, redis_client, _decision())


@pytest.mark.asyncio
async def test_build_risk_context_accepts_snapshot_within_max_age():
    borderline_snapshot = {
        "total_value_reference_currency": Decimal("1000"),
        "taken_at": datetime.now(tz=UTC) - timedelta(seconds=60),  # bien sous le seuil par défaut (300s)
    }
    pool, _ = _make_pool(
        fetchrow_by_key={**_COMMON_FETCHROW, "portfolio_snapshots": borderline_snapshot},
        fetch_by_key=_COMMON_FETCH,
    )
    redis_client = AsyncMock()
    redis_client.get.return_value = None

    context = await _build_risk_context(pool, redis_client, _decision())

    assert context.available_capital == Decimal("1000")


@pytest.mark.asyncio
async def test_evaluate_decision_records_blocked_outcome_without_raising():
    """Un capital inconnu doit produire un RiskOutcome bloqué et traçable,
    jamais une exception qui remonterait jusqu'à la boucle d'orchestration
    (execution_engine.main), conformément au principe de ne jamais arrêter
    la boucle globale pour une décision individuelle."""
    pool, _ = _make_pool(
        fetchrow_by_key={**_COMMON_FETCHROW, "portfolio_snapshots": None},
        fetch_by_key=_COMMON_FETCH,
    )
    redis_client = AsyncMock()
    redis_client.get.return_value = None
    published: list[tuple[str, dict]] = []

    def publish_journal_event(event_type: str, payload: dict) -> None:
        published.append((event_type, payload))

    outcome = await _evaluate_decision(pool, redis_client, _decision(), publish_journal_event)

    assert outcome.passed is False
    assert outcome.suggested_quantity is None
    assert len(published) == 1
    assert published[0][1]["passed"] is False


# --- Étape 5 (16/08/2026) : mur d'allocation en mode réel ---


@pytest.mark.asyncio
async def test_real_mode_applies_allocation_percentage_below_100():
    """Cas exact du mandat §11 : 350 USDT réels, 50% alloués -> 175 USDT
    exposés à risk_engine, jamais les 350 entiers."""
    fresh_snapshot = {
        "total_value_reference_currency": Decimal("350"),
        "taken_at": datetime.now(tz=UTC),
    }
    pool, _ = _make_pool(
        fetchrow_by_key={
            **_COMMON_FETCHROW,
            "portfolio_snapshots": fresh_snapshot,
            "capital_allocation_config": {"allocation_pct": Decimal("50.00")},
        },
        fetch_by_key=_COMMON_FETCH,
    )
    redis_client = AsyncMock()
    redis_client.get.return_value = None

    context = await _build_risk_context(pool, redis_client, _decision())

    assert context.available_capital == Decimal("175.00")


@pytest.mark.asyncio
async def test_real_mode_blocks_when_no_allocation_configured_for_exchange():
    """Mandat §11 : "Le système ne doit jamais pouvoir dépasser cette
    limite" - un exchange jamais explicitement configuré ne doit jamais
    se rabattre silencieusement sur 100% du solde réel."""
    fresh_snapshot = {
        "total_value_reference_currency": Decimal("350"),
        "taken_at": datetime.now(tz=UTC),
    }
    pool, _ = _make_pool(
        fetchrow_by_key={
            **_COMMON_FETCHROW,
            "portfolio_snapshots": fresh_snapshot,
            "capital_allocation_config": None,
        },
        fetch_by_key=_COMMON_FETCH,
    )
    redis_client = AsyncMock()
    redis_client.get.return_value = None

    with pytest.raises(PortfolioUnavailableError):
        await _build_risk_context(pool, redis_client, _decision())


# --- Étape 4 (16/08/2026) : capital Paper totalement indépendant du réel ---

_PAPER_FETCHROW = {
    "execution_mode_state": {"mode": "paper"},
    "ohlcv_candles_1m": {"close": Decimal("60000")},
    "order_book_snapshots": None,
    "AND exchange = $2 AND symbol = $3": None,
    "date_trunc('day'": {"total": Decimal("0")},
}


@pytest.mark.asyncio
async def test_paper_mode_never_reads_portfolio_snapshots():
    """Le bug corrigé précisément par ce chantier : avant, le mode paper
    lisait le solde RÉEL de l'exchange (portfolio_snapshots) pour
    dimensionner une position simulée. Si ce test appelle
    portfolio_snapshots par erreur, `_make_pool` lève une AssertionError
    (requête non attendue) - la meilleure garantie qu'on ne l'appelle
    plus jamais en mode paper."""
    pool, _ = _make_pool(
        fetchrow_by_key={
            **_PAPER_FETCHROW,
            "paper_capital_config": {"initial_capital": Decimal("1000"), "set_at": datetime.now(tz=UTC)},
            "execution_mode = 'paper' AND status = 'closed'": {"total": Decimal("0")},
        },
        fetch_by_key=_COMMON_FETCH,
    )
    redis_client = AsyncMock()
    redis_client.get.return_value = None

    context = await _build_risk_context(pool, redis_client, _decision())

    assert context.available_capital == Decimal("1000")


@pytest.mark.asyncio
async def test_paper_mode_capital_includes_realized_pnl_since_config():
    pool, _ = _make_pool(
        fetchrow_by_key={
            **_PAPER_FETCHROW,
            "paper_capital_config": {"initial_capital": Decimal("1000"), "set_at": datetime.now(tz=UTC)},
            "execution_mode = 'paper' AND status = 'closed'": {"total": Decimal("42.50")},
        },
        fetch_by_key=_COMMON_FETCH,
    )
    redis_client = AsyncMock()
    redis_client.get.return_value = None

    context = await _build_risk_context(pool, redis_client, _decision())

    assert context.available_capital == Decimal("1042.50")


@pytest.mark.asyncio
async def test_paper_mode_capital_reflects_losses_too():
    pool, _ = _make_pool(
        fetchrow_by_key={
            **_PAPER_FETCHROW,
            "paper_capital_config": {"initial_capital": Decimal("1000"), "set_at": datetime.now(tz=UTC)},
            "execution_mode = 'paper' AND status = 'closed'": {"total": Decimal("-30.00")},
        },
        fetch_by_key=_COMMON_FETCH,
    )
    redis_client = AsyncMock()
    redis_client.get.return_value = None

    context = await _build_risk_context(pool, redis_client, _decision())

    assert context.available_capital == Decimal("970.00")


@pytest.mark.asyncio
async def test_paper_mode_blocks_when_no_config_exists():
    pool, _ = _make_pool(
        fetchrow_by_key={**_PAPER_FETCHROW, "paper_capital_config": None},
        fetch_by_key=_COMMON_FETCH,
    )
    redis_client = AsyncMock()
    redis_client.get.return_value = None

    with pytest.raises(PortfolioUnavailableError):
        await _build_risk_context(pool, redis_client, _decision())


# --- Deux pools Paper séparés par market_type (18/08/2026) ---


@pytest.mark.asyncio
async def test_paper_mode_futures_decision_reads_futures_pool_not_spot():
    """Le cœur de ce chantier : une décision futures explicite
    (`decision["market_type"]="futures_perpetual"`, ex. liquidation_cascade)
    doit lire un pool DIFFÉRENT du pool spot - vérifié en donnant aux
    deux des valeurs de capital très différentes (1000 vs 50) et en
    confirmant que c'est bien la valeur FUTURES qui ressort."""

    async def fetchrow_side_effect(query, *args):
        if "execution_mode_state" in query:
            return {"mode": "paper"}
        if "ohlcv_candles_1m" in query:
            return {"close": Decimal("60000")}
        if "order_book_snapshots" in query:
            return None
        if "AND exchange = $2 AND symbol = $3" in query:
            return None
        if "date_trunc('day'" in query:
            return {"total": Decimal("0")}
        if "paper_capital_config" in query:
            # Le paramètre $1 distingue les deux pools - None (spot) vs
            # 'futures_perpetual' - vérifié directement ici plutôt que
            # supposé, pour être certain que le bon pool est interrogé.
            requested_market_type = args[0] if args else None
            if requested_market_type == "futures_perpetual":
                return {"initial_capital": Decimal("50"), "set_at": datetime.now(tz=UTC)}
            return {"initial_capital": Decimal("1000"), "set_at": datetime.now(tz=UTC)}
        if "execution_mode = 'paper' AND status = 'closed'" in query:
            return {"total": Decimal("0")}
        raise AssertionError(f"Requête fetchrow non attendue par le test : {query}")

    async def fetch_side_effect(query, *args):
        for key, value in _COMMON_FETCH.items():
            if key in query:
                return value
        raise AssertionError(f"Requête fetch non attendue par le test : {query}")

    conn = AsyncMock()
    conn.fetchrow.side_effect = fetchrow_side_effect
    conn.fetch.side_effect = fetch_side_effect
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    redis_client = AsyncMock()
    redis_client.get.return_value = None

    futures_context = await _build_risk_context(
        pool, redis_client, _decision(market_type="futures_perpetual")
    )
    assert futures_context.available_capital == Decimal("50")

    spot_context = await _build_risk_context(pool, redis_client, _decision(market_type=None))
    assert spot_context.available_capital == Decimal("1000")


@pytest.mark.asyncio
async def test_paper_mode_futures_pnl_never_mixed_with_spot_pnl():
    """Le P&L réalisé accumulé depuis la configuration doit lui aussi
    être filtré par market_type - une perte sur une position spot ne
    doit jamais réduire le pool futures, ni l'inverse."""

    async def fetchrow_side_effect(query, *args):
        if "execution_mode_state" in query:
            return {"mode": "paper"}
        if "ohlcv_candles_1m" in query:
            return {"close": Decimal("60000")}
        if "order_book_snapshots" in query:
            return None
        if "AND exchange = $2 AND symbol = $3" in query:
            return None
        if "date_trunc('day'" in query:
            return {"total": Decimal("0")}
        if "paper_capital_config" in query:
            return {"initial_capital": Decimal("1000"), "set_at": datetime.now(tz=UTC)}
        if "execution_mode = 'paper' AND status = 'closed'" in query:
            # Le 3e paramètre positionnel est market_type - vérifie
            # explicitement qu'il est bien transmis à CETTE requête,
            # pas seulement à celle de paper_capital_config.
            market_type_param = args[0] if args else None
            if market_type_param == "futures_perpetual":
                return {"total": Decimal("-500")}  # perte futures massive
            return {"total": Decimal("100")}  # gain spot, jamais contaminé
        raise AssertionError(f"Requête fetchrow non attendue par le test : {query}")

    async def fetch_side_effect(query, *args):
        for key, value in _COMMON_FETCH.items():
            if key in query:
                return value
        raise AssertionError(f"Requête fetch non attendue par le test : {query}")

    conn = AsyncMock()
    conn.fetchrow.side_effect = fetchrow_side_effect
    conn.fetch.side_effect = fetch_side_effect
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    redis_client = AsyncMock()
    redis_client.get.return_value = None

    spot_context = await _build_risk_context(pool, redis_client, _decision(market_type=None))
    assert spot_context.available_capital == Decimal("1100")  # 1000 + 100, jamais -500

    futures_context = await _build_risk_context(
        pool, redis_client, _decision(market_type="futures_perpetual")
    )
    assert futures_context.available_capital == Decimal("500")  # 1000 - 500, jamais +100
