"""Tests du data_normalizer (Phase 8)."""

import json
from decimal import Decimal

import pytest

from data_normalizer.main import TradeNormalizer
from shared.symbol_mapping import UnknownSymbolError, to_canonical


def _make_raw_trade(native_symbol, trade_id, ts_ms, price, amount, direction):
    return {
        "native_symbol": native_symbol,
        "payload": {
            "ch": f"market.{native_symbol}.trade.detail",
            "tick": {
                "data": [
                    {
                        "tradeId": trade_id,
                        "ts": ts_ms,
                        "price": price,
                        "amount": amount,
                        "direction": direction,
                    }
                ]
            },
        },
    }


def test_to_canonical_known_symbol():
    assert to_canonical("htx", "btcusdt") == "BTC/USDT"


def test_to_canonical_unknown_symbol_raises():
    with pytest.raises(UnknownSymbolError):
        to_canonical("htx", "dogeusdt")


def test_normalize_trade_message_produces_canonical_row():
    events = []
    normalizer = TradeNormalizer("htx", lambda t, p: events.append((t, p)))

    raw = _make_raw_trade(
        "btcusdt", trade_id=1, ts_ms=1_700_000_000_000, price="65000.5", amount="0.01", direction="buy"
    )
    rows = normalizer.normalize_trade_message(raw)

    assert len(rows) == 1
    assert rows[0]["symbol"] == "BTC/USDT"
    assert rows[0]["side"] == "buy"
    assert rows[0]["trade_id"] == "1"
    assert not events  # aucun événement de trou/erreur sur le premier trade


def test_duplicate_trade_id_is_ignored():
    normalizer = TradeNormalizer("htx", lambda t, p: None)
    raw = _make_raw_trade(
        "btcusdt", trade_id=42, ts_ms=1_700_000_000_000, price="65000", amount="0.01", direction="buy"
    )

    first = normalizer.normalize_trade_message(raw)
    second = normalizer.normalize_trade_message(raw)

    assert len(first) == 1
    assert len(second) == 0


def test_gap_detection_emits_journal_event():
    events = []
    normalizer = TradeNormalizer("htx", lambda t, p: events.append((t, p)))

    first = _make_raw_trade(
        "btcusdt", trade_id=1, ts_ms=1_700_000_000_000, price="65000", amount="0.01", direction="buy"
    )
    later = _make_raw_trade(
        "btcusdt",
        trade_id=2,
        ts_ms=1_700_000_000_000 + 120_000,
        price="65010",
        amount="0.01",
        direction="buy",
    )

    normalizer.normalize_trade_message(first)
    normalizer.normalize_trade_message(later)

    gap_events = [e for e in events if e[0] == "data.gap_detected"]
    assert len(gap_events) == 1
    assert gap_events[0][1]["gap_seconds"] == pytest.approx(120.0)


def test_unknown_symbol_is_reported_and_skipped():
    events = []
    normalizer = TradeNormalizer("htx", lambda t, p: events.append((t, p)))

    raw = _make_raw_trade(
        "dogeusdt", trade_id=1, ts_ms=1_700_000_000_000, price="0.1", amount="100", direction="buy"
    )
    rows = normalizer.normalize_trade_message(raw)

    assert rows == []
    assert any(e[0] == "normalizer.unknown_symbol" for e in events)


# --- Binance (correctif du 18/08/2026) ---
#
# Bug réel trouvé en diagnostiquant pourquoi Binance, actif dans
# ACTIVE_EXCHANGES depuis des heures, n'avait jamais produit une seule
# ligne dans raw_market_data : normalize_trade_message/
# normalize_order_book_message ne savaient parser QUE le format HTX -
# aucun test n'exerçait jamais le chemin Binance, exactement comme la
# fonction elle-même. Les exemples ci-dessous reproduisent au caractère
# près les payloads de la documentation Binance Open Platform (Trade
# Streams pour <symbol>@trade, PAS @aggTrade ; Partial Book Depth
# Streams pour <symbol>@depth20@100ms), vérifiés indépendamment avant
# d'écrire le correctif - jamais déduits du format HTX par analogie.


def _make_binance_raw_trade(native_symbol, trade_id, trade_time_ms, price, quantity, is_buyer_maker):
    """Payload exact du flux <symbol>@trade (pas @aggTrade)."""
    return {
        "native_symbol": native_symbol,
        "payload": {
            "e": "trade",
            "E": trade_time_ms,
            "s": native_symbol.upper(),
            "t": trade_id,
            "p": price,
            "q": quantity,
            "b": 88,
            "a": 50,
            "T": trade_time_ms,
            "m": is_buyer_maker,
            "M": True,
        },
    }


def test_normalize_binance_trade_message_produces_canonical_row():
    events = []
    normalizer = TradeNormalizer("binance", lambda t, p: events.append((t, p)))

    raw = _make_binance_raw_trade(
        "btcusdt",
        trade_id=12345,
        trade_time_ms=1_700_000_000_000,
        price="65000.5",
        quantity="0.01",
        is_buyer_maker=False,
    )
    rows = normalizer.normalize_trade_message(raw)

    assert len(rows) == 1
    assert rows[0]["exchange"] == "binance"
    assert rows[0]["symbol"] == "BTC/USDT"
    assert rows[0]["trade_id"] == "12345"
    assert rows[0]["price"] == Decimal("65000.5")
    assert rows[0]["quantity"] == Decimal("0.01")
    assert not events


def test_normalize_binance_trade_message_side_matches_is_buyer_maker_convention():
    """m=true ('is the buyer the market maker') -> le vendeur était
    l'agresseur -> côté SELL. m=false -> l'acheteur était l'agresseur
    -> côté BUY. Vérifié explicitement, jamais supposé par analogie
    avec le champ `direction` de HTX (sémantique différente)."""
    normalizer = TradeNormalizer("binance", lambda t, p: None)

    maker_buyer = _make_binance_raw_trade(
        "btcusdt",
        trade_id=1,
        trade_time_ms=1_700_000_000_000,
        price="65000",
        quantity="0.01",
        is_buyer_maker=True,
    )
    taker_buyer = _make_binance_raw_trade(
        "btcusdt",
        trade_id=2,
        trade_time_ms=1_700_000_000_000,
        price="65000",
        quantity="0.01",
        is_buyer_maker=False,
    )

    assert normalizer.normalize_trade_message(maker_buyer)[0]["side"] == "sell"
    assert normalizer.normalize_trade_message(taker_buyer)[0]["side"] == "buy"


def test_normalize_binance_trade_message_never_produces_a_silent_empty_list():
    """Le cœur du bug corrigé : avant, un message Binance authentique
    (structure ci-dessus, jamais 'tick.data[]') produisait une liste
    vide sans exception ni événement journalisé - indétectable sans
    creuser jusqu'à raw_market_data en base. Ce test échoue si la
    régression revient."""
    normalizer = TradeNormalizer("binance", lambda t, p: None)
    raw = _make_binance_raw_trade(
        "ethusdt",
        trade_id=999,
        trade_time_ms=1_700_000_000_000,
        price="3000",
        quantity="1",
        is_buyer_maker=False,
    )

    rows = normalizer.normalize_trade_message(raw)

    assert len(rows) == 1, "Régression : un message Binance authentique ne produit plus aucune ligne."


def test_normalize_binance_order_book_message_reads_bids_asks_at_payload_root():
    """<symbol>@depth20@100ms : bids/asks à la racine du payload,
    jamais sous une clé 'tick' (spécifique à HTX)."""
    normalizer = TradeNormalizer("binance", lambda t, p: None)
    raw = {
        "native_symbol": "btcusdt",
        "payload": {
            "lastUpdateId": 160,
            "bids": [["64999.5", "0.5"], ["64999.0", "1.2"]],
            "asks": [["65000.5", "0.3"], ["65001.0", "0.9"]],
        },
    }

    row = normalizer.normalize_order_book_message(raw)

    assert row is not None
    assert row["exchange"] == "binance"
    assert row["symbol"] == "BTC/USDT"
    assert json.loads(row["bids"]) == [["64999.5", "0.5"], ["64999.0", "1.2"]]
    assert json.loads(row["asks"]) == [["65000.5", "0.3"], ["65001.0", "0.9"]]


def test_normalize_binance_order_book_message_returns_none_when_malformed():
    normalizer = TradeNormalizer("binance", lambda t, p: None)
    raw = {"native_symbol": "btcusdt", "payload": {"lastUpdateId": 160}}  # bids/asks absents

    assert normalizer.normalize_order_book_message(raw) is None
