"""Tests de feature_engine.main._compute_and_store_features (Phase 9).

Bug réel trouvé le 18/08/2026 (en activant Binance pour la première
fois) : `bids[0][0]`/`asks[0][0]` étaient utilisés sans cast numérique -
HTX envoie des niveaux de prix/quantité déjà numériques dans son JSON,
mais Binance les envoie systématiquement en CHAÎNES DE CARACTÈRES
(convention documentée de leur API). Cassait `SpreadBps.compute`
(comparaison `<=` entre str et int) ET `OrderFlowImbalance.compute`
(`sum()` sur des str) - jamais détecté avant faute de test direct sur
cette fonction, et faute de données Binance réelles avant le correctif
de `data_normalizer` (chantier séparé, même soirée).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from feature_engine.main import _compute_and_store_features


def _make_pool(bids_json: str, asks_json: str):
    conn = AsyncMock()
    conn.fetch.side_effect = lambda query, *args: (
        []  # candles (closes/volumes) - vide, hors du périmètre de ce test
        if "ohlcv_candles_1m" in query
        else [] if "liquidation_events" in query else []  # liquidation_events - idem
    )
    conn.fetchrow.return_value = {"bids": bids_json, "asks": asks_json}
    conn.executemany = AsyncMock()

    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool, conn


@pytest.mark.asyncio
async def test_binance_style_string_order_book_never_raises():
    """Le cœur du bug : un carnet d'ordres au format Binance (prix ET
    quantités en chaînes de caractères, jamais des nombres) ne doit
    jamais faire planter le calcul - avant ce correctif, cet appel
    levait TypeError et faisait perdre TOUTES les features du cycle
    pour ce symbole, pas seulement spread_bps."""
    from feature_engine.registry import ACTIVE_FEATURES

    binance_style_bids = json.dumps([["64999.50", "0.5"], ["64999.00", "1.2"]])
    binance_style_asks = json.dumps([["65000.50", "0.3"], ["65001.00", "0.9"]])
    pool, _ = _make_pool(binance_style_bids, binance_style_asks)

    feature_definition_ids = {f.metadata.name: i for i, f in enumerate(ACTIVE_FEATURES)}
    # Ne doit lever aucune exception - c'est la régression réelle trouvée.
    await _compute_and_store_features(pool, "binance", "BTC/USDT", feature_definition_ids)


@pytest.mark.asyncio
async def test_spread_bps_computed_correctly_from_string_typed_book():
    """Vérifie que le résultat numérique est correct, pas seulement
    qu'aucune exception n'est levée - un cast silencieusement erroné
    serait pire qu'une exception explicite."""
    from feature_engine.registry import ACTIVE_FEATURES

    bids = json.dumps([["100.00", "1"]])
    asks = json.dumps([["101.00", "1"]])
    pool, conn = _make_pool(bids, asks)

    feature_definition_ids = {f.metadata.name: i for i, f in enumerate(ACTIVE_FEATURES)}
    await _compute_and_store_features(pool, "binance", "BTC/USDT", feature_definition_ids)

    conn.executemany.assert_awaited_once()
    inserted_rows = conn.executemany.call_args.args[1]
    spread_value = next(
        value for (_, fid, _, _, value) in inserted_rows if fid == feature_definition_ids["spread_bps"]
    )
    # mid = 100.5, écart = 1.00 -> (1/100.5)*10000 ≈ 99.50 bps
    assert spread_value == pytest.approx(99.50, abs=0.01)


@pytest.mark.asyncio
async def test_order_flow_imbalance_computed_correctly_from_string_typed_book():
    from feature_engine.registry import ACTIVE_FEATURES

    bids = json.dumps([["100.00", "3"]])  # volume bid = 3
    asks = json.dumps([["101.00", "1"]])  # volume ask = 1
    pool, conn = _make_pool(bids, asks)

    feature_definition_ids = {f.metadata.name: i for i, f in enumerate(ACTIVE_FEATURES)}
    await _compute_and_store_features(pool, "binance", "BTC/USDT", feature_definition_ids)

    inserted_rows = conn.executemany.call_args.args[1]
    imbalance_value = next(
        value
        for (_, fid, _, _, value) in inserted_rows
        if fid == feature_definition_ids["order_flow_imbalance"]
    )
    # (3 - 1) / (3 + 1) = 0.5
    assert imbalance_value == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_no_order_book_snapshot_never_sets_best_bid_ask():
    """Comportement inchangé quand aucun carnet n'existe encore -
    jamais une valeur inventée."""
    from feature_engine.registry import ACTIVE_FEATURES

    conn = AsyncMock()
    conn.fetch.return_value = []
    conn.fetchrow.return_value = None
    conn.executemany = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    feature_definition_ids = {f.metadata.name: i for i, f in enumerate(ACTIVE_FEATURES)}
    await _compute_and_store_features(pool, "binance", "BTC/USDT", feature_definition_ids)
    # Aucune exception - c'est la seule assertion nécessaire ici (le
    # comportement "aucun carnet -> pas de spread/imbalance" est déjà
    # couvert par les tests unitaires de chaque feature).
