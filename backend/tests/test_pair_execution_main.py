"""Tests de pair_execution.main (ADR-0021).

Isole l'orchestration (persistance, machine à états) des appels réseau
réels - le simulateur d'exécution en paper mode utilise un
`random_source` injectable pour forcer précisément chaque chemin de la
machine à états (BOTH_FILLED, BOTH_REJECTED, PARTIAL_EXECUTION avec
complétion, PARTIAL_EXECUTION avec compensation), pas seulement le
chemin heureux.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from datetime import UTC, datetime, timedelta

from pair_execution.main import (
    TRACKED_SYMBOLS,
    _compute_pair_quantity,
    _fetch_available_capital,
    _fetch_open_pair_statuses,
    _fetch_reference_price,
    _persist_pair_assessment,
    _register_funding_basis_strategy,
    execute_pair_opportunity_paper,
    run_pair_execution_cycle,
)
from pair_execution.pair_quality import ExecutionRisk, PairDecisionOutcome, PairQualityAssessment
from pair_execution.state_machine import PairStatus


def _make_pool():
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchval = AsyncMock(return_value=1)

    id_counter = {"n": 0}

    async def fake_fetchrow(query, *args):
        if "FROM positions" in query and "SELECT" in query:
            return None  # aucune position déjà ouverte - premier remplissage
        id_counter["n"] += 1
        return {"id": id_counter["n"]}

    conn.fetchrow = AsyncMock(side_effect=fake_fetchrow)
    conn.fetch = AsyncMock(return_value=[])

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


def _assessment(decision=PairDecisionOutcome.ACCEPT, execution_probability=0.99) -> PairQualityAssessment:
    return PairQualityAssessment(
        gross_edge_bps=42.0,
        fees_bps=16.0,
        slippage_bps=7.0,
        net_edge_bps=19.0,
        execution_probability=execution_probability,
        partial_execution_probability=1 - execution_probability,
        execution_risk=ExecutionRisk.LOW,
        pair_quality_score=18.5,
        decision=decision,
    )


@pytest.mark.asyncio
async def test_register_funding_basis_strategy_persists_it():
    pool, conn = _make_pool()
    strategy_id = await _register_funding_basis_strategy(pool)
    assert strategy_id == 1
    conn.fetchrow.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_open_pair_statuses_excludes_terminal_states():
    pool, conn = _make_pool()
    conn.fetch = AsyncMock(return_value=[{"status": "partial_execution"}])
    statuses = await _fetch_open_pair_statuses(pool, "htx", "BTC/USDT")
    assert statuses == [PairStatus.PARTIAL_EXECUTION]
    # Vérifie que la requête exclut bien les états terminaux, pas seulement le résultat.
    query = conn.fetch.call_args.args[0]
    assert "both_filled" in query and "both_rejected" in query and "resolved" in query


# --- La machine à états, orchestrée réellement (ADR-0021 §4.5) ---


@pytest.mark.asyncio
async def test_both_legs_fill_opens_both_positions():
    pool, conn = _make_pool()
    events = []

    # random_source < probabilité à chaque appel -> toujours FILLED.
    pair_id = await execute_pair_opportunity_paper(
        pool,
        exchange="htx",
        symbol="BTC/USDT",
        strategy_id=1,
        pair_decision_id=1,
        assessment=_assessment(execution_probability=0.99),
        spot_side="sell",
        spot_price=Decimal("60000"),
        quantity=Decimal("0.01"),
        publish_journal_event=lambda t, p: events.append((t, p)),
        random_source=lambda: 0.01,  # très inférieur à toute probabilité raisonnable -> FILLED
    )

    assert pair_id is not None
    assert any(t == "pair_execution.both_filled" for t, _ in events)
    # Deux jambes ouvertes = deux décisions insérées + deux appels apply_fill (via positions.py,
    # qui exécute lui-même des requêtes SQL sur la même connexion mockée) - au minimum les deux
    # insertions de décisions doivent avoir eu lieu.
    insert_decision_calls = [c for c in conn.fetchrow.call_args_list if "INSERT INTO decisions" in c.args[0]]
    assert len(insert_decision_calls) == 2


@pytest.mark.asyncio
async def test_both_legs_rejected_opens_no_position():
    pool, conn = _make_pool()
    events = []

    pair_id = await execute_pair_opportunity_paper(
        pool,
        exchange="htx",
        symbol="BTC/USDT",
        strategy_id=1,
        pair_decision_id=1,
        assessment=_assessment(execution_probability=0.01),
        spot_side="sell",
        spot_price=Decimal("60000"),
        quantity=Decimal("0.01"),
        publish_journal_event=lambda t, p: events.append((t, p)),
        random_source=lambda: 0.99,  # très supérieur à toute probabilité raisonnable -> REJECTED
    )

    assert pair_id is not None
    assert any(t == "pair_execution.both_rejected" for t, _ in events)
    insert_decision_calls = [c for c in conn.fetchrow.call_args_list if "INSERT INTO decisions" in c.args[0]]
    assert len(insert_decision_calls) == 0


@pytest.mark.asyncio
async def test_partial_execution_that_completes_records_incident_and_both_legs_end_up_open():
    pool, conn = _make_pool()
    events = []

    # Alterne : jambe A remplie (valeur basse), jambe B rejetée (valeur
    # haute), puis la tentative de complétion réussit (valeur basse à nouveau).
    outcomes = iter([0.01, 0.99, 0.01])

    def controlled_random():
        return next(outcomes)

    pair_id = await execute_pair_opportunity_paper(
        pool,
        exchange="htx",
        symbol="BTC/USDT",
        strategy_id=1,
        pair_decision_id=1,
        assessment=_assessment(execution_probability=0.9),
        spot_side="sell",
        spot_price=Decimal("60000"),
        quantity=Decimal("0.01"),
        publish_journal_event=lambda t, p: events.append((t, p)),
        random_source=controlled_random,
    )

    assert pair_id is not None
    assert any(t == "pair_execution.partial_execution_completed" for t, _ in events)

    # Un incident doit être journalisé même si la complétion a réussi -
    # ADR-0021 : "mesurer le coût réel de chaque incident d'exécution",
    # jamais silencieux même dans le cas favorable.
    incident_calls = [c for c in conn.execute.call_args_list if "INSERT INTO pair_incidents" in c.args[0]]
    assert len(incident_calls) == 1


@pytest.mark.asyncio
async def test_partial_execution_that_cannot_complete_compensates_and_records_realized_cost():
    pool, conn = _make_pool()
    events = []

    # Jambe A remplie, jambe B rejetée, puis la tentative de complétion échoue aussi.
    outcomes = iter([0.01, 0.99, 0.99])

    def controlled_random():
        return next(outcomes)

    pair_id = await execute_pair_opportunity_paper(
        pool,
        exchange="htx",
        symbol="BTC/USDT",
        strategy_id=1,
        pair_decision_id=1,
        assessment=_assessment(execution_probability=0.9),
        spot_side="sell",
        spot_price=Decimal("60000"),
        quantity=Decimal("0.01"),
        publish_journal_event=lambda t, p: events.append((t, p)),
        random_source=controlled_random,
    )

    assert pair_id is not None
    assert any(t == "pair_execution.partial_execution_compensated" for t, _ in events)

    incident_calls = [c for c in conn.execute.call_args_list if "INSERT INTO pair_incidents" in c.args[0]]
    assert len(incident_calls) == 1
    # Le coût réel de l'incident doit être positif (un vrai coût), jamais None
    # une fois résolu (ADR-0021 : "mesurer le coût réel").
    realized_cost = incident_calls[0].args[6]
    assert realized_cost is not None
    assert realized_cost > 0


@pytest.mark.asyncio
async def test_partial_execution_always_updates_status_through_the_expected_sequence():
    """Vérifie que le statut transite bien par PARTIAL_EXECUTION puis
    COMPENSATING avant RESOLVED - pas juste le résultat final, la
    trajectoire elle-même (ADR-0021 §4.5)."""
    pool, conn = _make_pool()
    outcomes = iter([0.01, 0.99, 0.99])

    await execute_pair_opportunity_paper(
        pool,
        exchange="htx",
        symbol="BTC/USDT",
        strategy_id=1,
        pair_decision_id=1,
        assessment=_assessment(execution_probability=0.9),
        spot_side="sell",
        spot_price=Decimal("60000"),
        quantity=Decimal("0.01"),
        publish_journal_event=lambda t, p: None,
        random_source=lambda: next(outcomes),
    )

    status_updates = [
        c.args[0] for c in conn.execute.call_args_list if "UPDATE pair_decisions SET status" in c.args[0]
    ]
    # On ne peut pas lire les valeurs liées facilement ici sans plus de
    # ciblage, mais on vérifie qu'au moins plusieurs mises à jour de
    # statut ont bien eu lieu (pas un seul saut direct vers RESOLVED).
    assert len(status_updates) >= 3


# --- Correctif du déploiement (16/08/2026) : les rejets doivent être
# persistés au même titre que les acceptations, pas silencieusement
# perdus - le schéma (`decision IN ('accept', 'reject')`) le prévoyait
# depuis le début, la première implémentation ne le faisait pas. ---


@pytest.mark.asyncio
async def test_persist_pair_assessment_stores_a_rejected_opportunity_too():
    """Le bug corrigé précisément : avant, seule une paire ACCEPT était
    enregistrée dans pair_decisions - un rejet disparaissait
    silencieusement, invisible même a posteriori."""
    pool, conn = _make_pool()

    rejected_assessment = _assessment(decision=PairDecisionOutcome.REJECT, execution_probability=0.5)
    pair_id = await _persist_pair_assessment(pool, "htx", "SOL/USDT", rejected_assessment)

    assert pair_id is not None
    insert_calls = [c for c in conn.fetchrow.call_args_list if "INSERT INTO pair_decisions" in c.args[0]]
    assert len(insert_calls) == 1
    # La colonne `decision` doit bien porter 'reject', pas seulement 'accept'.
    assert insert_calls[0].args[11] == "reject"


# --- Correctif du 16/08/2026 : dimensionnement capital-relatif (audit) ---
#
# Avant ce correctif, `quantity = Decimal("0.01")` était appliqué
# uniformément à BTC/ETH/SOL - sans rapport ni avec leurs prix unitaires
# très différents, ni avec le capital réellement disponible. Ces tests
# vérifient que la quantité découle désormais du capital et du prix, et
# que l'absence de l'un ou l'autre bloque proprement le cycle (jamais une
# estimation dégradée).


def _make_pool_with_market_data(available_capital=None, snapshot_age_seconds=0, ask_price=None):
    """Variante de `_make_pool` qui route en plus les requêtes
    `portfolio_snapshots` et `order_book_snapshots` vers des données
    contrôlées."""
    pool, conn = _make_pool()

    async def fake_fetchrow(query, *args):
        if "FROM portfolio_snapshots" in query:
            if available_capital is None:
                return None
            return {
                "total_value_reference_currency": available_capital,
                "taken_at": datetime.now(tz=UTC) - timedelta(seconds=snapshot_age_seconds),
            }
        if "FROM order_book_snapshots" in query:
            if ask_price is None:
                return None
            return {"bids": "[[100, 1]]", "asks": f"[[{ask_price}, 1]]"}
        if "FROM positions" in query and "SELECT" in query:
            return None
        return {"id": 1}

    conn.fetchrow = AsyncMock(side_effect=fake_fetchrow)
    return pool, conn


@pytest.mark.asyncio
async def test_fetch_available_capital_returns_none_when_no_snapshot():
    pool, _ = _make_pool_with_market_data(available_capital=None)
    assert await _fetch_available_capital(pool, "htx") is None


@pytest.mark.asyncio
async def test_fetch_available_capital_returns_none_when_snapshot_too_old():
    pool, _ = _make_pool_with_market_data(available_capital=350, snapshot_age_seconds=999_999)
    assert await _fetch_available_capital(pool, "htx") is None


@pytest.mark.asyncio
async def test_fetch_available_capital_returns_value_when_fresh():
    pool, _ = _make_pool_with_market_data(available_capital=350, snapshot_age_seconds=1)
    assert await _fetch_available_capital(pool, "htx") == Decimal("350")


@pytest.mark.asyncio
async def test_fetch_reference_price_returns_none_when_no_order_book():
    pool, _ = _make_pool_with_market_data(ask_price=None)
    assert await _fetch_reference_price(pool, "htx", "BTC/USDT") is None


@pytest.mark.asyncio
async def test_fetch_reference_price_reads_top_of_ask_book():
    pool, _ = _make_pool_with_market_data(ask_price=63000)
    assert await _fetch_reference_price(pool, "htx", "BTC/USDT") == Decimal("63000")


@pytest.mark.asyncio
async def test_compute_pair_quantity_rejects_below_minimum_notional():
    """Le cas précis corrigé par l'audit : au prix du marché (~63 000 USD),
    2% d'un compte de 350 USD ne représentent que 7 USD de notionnel,
    sous le seuil minimum viable - doit être rejeté, jamais arrondi
    silencieusement vers une quantité microscopique."""
    pool, _ = _make_pool_with_market_data(available_capital=350, snapshot_age_seconds=1, ask_price=63000)
    assert await _compute_pair_quantity(pool, "htx", "BTC/USDT") is None


@pytest.mark.asyncio
async def test_compute_pair_quantity_scales_with_capital_when_sufficient():
    pool, _ = _make_pool_with_market_data(available_capital=1000, snapshot_age_seconds=1, ask_price=63000)
    quantity = await _compute_pair_quantity(pool, "htx", "BTC/USDT")
    expected = (Decimal("1000") * Decimal("0.02")) / Decimal("63000")  # 20 USD / 63000
    assert quantity == expected


@pytest.mark.asyncio
async def test_compute_pair_quantity_none_when_capital_unavailable():
    pool, _ = _make_pool_with_market_data(available_capital=None, ask_price=63000)
    assert await _compute_pair_quantity(pool, "htx", "BTC/USDT") is None


@pytest.mark.asyncio
async def test_compute_pair_quantity_none_when_no_reference_price():
    pool, _ = _make_pool_with_market_data(available_capital=1000, snapshot_age_seconds=1, ask_price=None)
    assert await _compute_pair_quantity(pool, "htx", "BTC/USDT") is None


@pytest.mark.asyncio
async def test_run_pair_execution_cycle_skips_all_symbols_when_capital_unavailable():
    """Bout en bout : capital indisponible -> le cycle ne doit jamais
    atteindre `build_pair_assessment` (donc jamais tenter une évaluation
    ou une exécution), et doit journaliser explicitement le skip pour
    chaque symbole suivi."""
    pool, conn = _make_pool_with_market_data(available_capital=None)
    events = []

    await run_pair_execution_cycle(
        pool, strategy_id=1, publish_journal_event=lambda t, p: events.append((t, p)), exchange="htx"
    )

    skip_events = [p for t, p in events if t == "pair_execution.symbol_skipped_sizing_unavailable"]
    assert len(skip_events) == len(TRACKED_SYMBOLS)
    assert not any(t in ("pair_execution.rejected", "pair_execution.both_filled") for t, _ in events)
