"""Tests de data_collector.adapters.binance_futures.BinanceFuturesAdapter
(Étapes 7-8 du plan validé le 16/08/2026).

Même niveau de couverture que test_htx_futures_adapter.py : les
garde-fous d'authentification, l'invariant de levier 1x (ADR-0018), et
la gestion des codes d'erreur "déjà configuré" de Binance - pas les
appels réseau réels.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from data_collector.adapters.binance_futures import BinanceFuturesAdapter, parse_liquidation_message
from shared.futures_adapter import PositionSide


@pytest.mark.asyncio
async def test_place_order_without_api_keys_raises_runtime_error():
    adapter = BinanceFuturesAdapter()
    with pytest.raises(RuntimeError, match="Clés API Binance Futures non configurées"):
        await adapter.place_order("BTC/USDT", PositionSide.LONG, Decimal("0.01"))
    await adapter.close()


@pytest.mark.asyncio
async def test_close_position_without_api_keys_raises_runtime_error():
    adapter = BinanceFuturesAdapter()
    with pytest.raises(RuntimeError, match="Clés API Binance Futures non configurées"):
        await adapter.close_position("BTC/USDT", PositionSide.LONG, Decimal("0.01"))
    await adapter.close()


@pytest.mark.asyncio
async def test_get_positions_without_api_keys_raises_runtime_error():
    adapter = BinanceFuturesAdapter()
    with pytest.raises(RuntimeError, match="Clés API Binance Futures non configurées"):
        await adapter.get_positions("BTC/USDT")
    await adapter.close()


@pytest.mark.asyncio
async def test_get_positions_filters_flat_entries_and_maps_side():
    adapter = BinanceFuturesAdapter(api_key="test-key", api_secret="test-secret")

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = [
        {
            "positionAmt": "0.010",
            "entryPrice": "60000.0",
            "markPrice": "60100.0",
            "unRealizedProfit": "1.0",
        }
    ]
    adapter._http_client.get = AsyncMock(return_value=fake_response)

    positions = await adapter.get_positions("BTC/USDT")

    assert len(positions) == 1
    assert positions[0].side == PositionSide.LONG
    assert positions[0].quantity == Decimal("0.010")


@pytest.mark.asyncio
async def test_get_positions_flat_entry_is_excluded():
    adapter = BinanceFuturesAdapter(api_key="test-key", api_secret="test-secret")

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = [
        {"positionAmt": "0", "entryPrice": "0", "markPrice": "60000", "unRealizedProfit": "0"}
    ]
    adapter._http_client.get = AsyncMock(return_value=fake_response)

    positions = await adapter.get_positions("BTC/USDT")

    assert positions == []


@pytest.mark.asyncio
async def test_get_positions_maps_short_side_from_negative_amount():
    adapter = BinanceFuturesAdapter(api_key="test-key", api_secret="test-secret")

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = [
        {"positionAmt": "-0.010", "entryPrice": "60000", "markPrice": "59900", "unRealizedProfit": "1.0"}
    ]
    adapter._http_client.get = AsyncMock(return_value=fake_response)

    positions = await adapter.get_positions("BTC/USDT")

    assert positions[0].side == PositionSide.SHORT
    assert positions[0].quantity == Decimal("0.010")  # toujours positive, même pour un short


@pytest.mark.asyncio
async def test_place_order_forces_leverage_to_one_before_ordering():
    """Invariant ADR-0018 : jamais un ordre sans avoir explicitement
    fixé le levier du compte à 1x juste avant."""
    adapter = BinanceFuturesAdapter(api_key="test-key", api_secret="test-secret")

    leverage_response = MagicMock()
    leverage_response.raise_for_status = MagicMock()
    order_response = MagicMock()
    order_response.raise_for_status = MagicMock()
    order_response.json.return_value = {"orderId": 12345}

    calls = []

    async def fake_post(path, params=None, headers=None):
        calls.append((path, params))
        return leverage_response if path == "/fapi/v1/leverage" else order_response

    adapter._http_client.post = AsyncMock(side_effect=fake_post)

    order_id = await adapter.place_order("BTC/USDT", PositionSide.LONG, Decimal("0.01"))

    assert order_id == "12345"
    assert calls[0][0] == "/fapi/v1/leverage"
    assert calls[0][1]["leverage"] == 1
    assert calls[1][0] == "/fapi/v1/order"
    assert calls[1][1]["side"] == "BUY"


@pytest.mark.asyncio
async def test_close_position_sets_reduce_only():
    adapter = BinanceFuturesAdapter(api_key="test-key", api_secret="test-secret")

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"orderId": 999}
    adapter._http_client.post = AsyncMock(return_value=fake_response)

    await adapter.close_position("BTC/USDT", PositionSide.LONG, Decimal("0.01"))

    _, kwargs = adapter._http_client.post.call_args
    assert kwargs["params"]["reduceOnly"] == "true"
    assert kwargs["params"]["side"] == "SELL"  # clôture d'un LONG = vente


@pytest.mark.asyncio
async def test_get_funding_rate_requires_no_authentication():
    adapter = BinanceFuturesAdapter()  # pas de clés - doit fonctionner quand même

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"symbol": "BTCUSDT", "lastFundingRate": "0.000123"}
    adapter._http_client.get = AsyncMock(return_value=fake_response)

    rate = await adapter.get_funding_rate("BTC/USDT")

    assert rate == Decimal("0.000123")
    await adapter.close()


# --- Configuration du compte : gestion des codes "déjà configuré" ---


@pytest.mark.asyncio
async def test_set_one_way_position_mode_ignores_already_configured_error():
    adapter = BinanceFuturesAdapter(api_key="test-key", api_secret="test-secret")

    fake_response = MagicMock()
    fake_response.status_code = 400
    fake_response.json.return_value = {"code": -4059, "msg": "No need to change position side."}
    fake_response.raise_for_status = MagicMock(side_effect=AssertionError("ne doit jamais être appelé"))
    adapter._http_client.post = AsyncMock(return_value=fake_response)

    await adapter.set_one_way_position_mode()  # ne doit pas lever


@pytest.mark.asyncio
async def test_set_one_way_position_mode_raises_on_other_errors():
    adapter = BinanceFuturesAdapter(api_key="test-key", api_secret="test-secret")

    fake_response = MagicMock()
    fake_response.status_code = 401
    fake_response.json.return_value = {"code": -2015, "msg": "Invalid API-key."}
    fake_response.raise_for_status = MagicMock(side_effect=RuntimeError("401"))
    adapter._http_client.post = AsyncMock(return_value=fake_response)

    with pytest.raises(RuntimeError):
        await adapter.set_one_way_position_mode()


@pytest.mark.asyncio
async def test_set_isolated_margin_ignores_already_configured_error():
    adapter = BinanceFuturesAdapter(api_key="test-key", api_secret="test-secret")

    fake_response = MagicMock()
    fake_response.status_code = 400
    fake_response.json.return_value = {"code": -4046, "msg": "No need to change margin type."}
    fake_response.raise_for_status = MagicMock(side_effect=AssertionError("ne doit jamais être appelé"))
    adapter._http_client.post = AsyncMock(return_value=fake_response)

    await adapter.set_isolated_margin("BTC/USDT")  # ne doit pas lever


# --- Triptyque d'ordres (Étape 9, 16/08/2026) ---


@pytest.mark.asyncio
async def test_place_stop_loss_closes_entire_position_at_market():
    adapter = BinanceFuturesAdapter(api_key="test-key", api_secret="test-secret")

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"orderId": 555}
    adapter._http_client.post = AsyncMock(return_value=fake_response)

    order_id = await adapter.place_stop_loss("BTC/USDT", PositionSide.LONG, Decimal("58000"))

    assert order_id == "555"
    _, kwargs = adapter._http_client.post.call_args
    assert kwargs["params"]["type"] == "STOP_MARKET"
    assert kwargs["params"]["stopPrice"] == "58000"
    assert kwargs["params"]["closePosition"] == "true"
    assert kwargs["params"]["side"] == "SELL"  # protège un LONG -> se déclenche par une vente


@pytest.mark.asyncio
async def test_place_stop_loss_for_short_position_uses_buy_side():
    adapter = BinanceFuturesAdapter(api_key="test-key", api_secret="test-secret")

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {"orderId": 556}
    adapter._http_client.post = AsyncMock(return_value=fake_response)

    await adapter.place_stop_loss("BTC/USDT", PositionSide.SHORT, Decimal("62000"))

    _, kwargs = adapter._http_client.post.call_args
    assert kwargs["params"]["side"] == "BUY"


@pytest.mark.asyncio
async def test_place_stop_loss_without_api_keys_raises_runtime_error():
    adapter = BinanceFuturesAdapter()
    with pytest.raises(RuntimeError, match="Clés API Binance Futures non configurées"):
        await adapter.place_stop_loss("BTC/USDT", PositionSide.LONG, Decimal("58000"))
    await adapter.close()


@pytest.mark.asyncio
async def test_cancel_order_sends_delete_request():
    adapter = BinanceFuturesAdapter(api_key="test-key", api_secret="test-secret")

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.raise_for_status = MagicMock()
    adapter._http_client.delete = AsyncMock(return_value=fake_response)

    await adapter.cancel_order("BTC/USDT", "555")

    _, kwargs = adapter._http_client.delete.call_args
    assert kwargs["params"]["orderId"] == "555"


@pytest.mark.asyncio
async def test_cancel_order_ignores_unknown_order_error():
    """Code -2011 : l'ordre est déjà annulé/exécuté/expiré - l'objectif
    ("plus d'ordre conditionnel en attente") est déjà atteint, jamais un
    échec réel pour cet appelant."""
    adapter = BinanceFuturesAdapter(api_key="test-key", api_secret="test-secret")

    fake_response = MagicMock()
    fake_response.status_code = 400
    fake_response.json.return_value = {"code": -2011, "msg": "Unknown order sent."}
    fake_response.raise_for_status = MagicMock(side_effect=AssertionError("ne doit jamais être appelé"))
    adapter._http_client.delete = AsyncMock(return_value=fake_response)

    await adapter.cancel_order("BTC/USDT", "555")  # ne doit pas lever


@pytest.mark.asyncio
async def test_cancel_order_raises_on_other_errors():
    adapter = BinanceFuturesAdapter(api_key="test-key", api_secret="test-secret")

    fake_response = MagicMock()
    fake_response.status_code = 401
    fake_response.json.return_value = {"code": -2015, "msg": "Invalid API-key."}
    fake_response.raise_for_status = MagicMock(side_effect=RuntimeError("401"))
    adapter._http_client.delete = AsyncMock(return_value=fake_response)

    with pytest.raises(RuntimeError):
        await adapter.cancel_order("BTC/USDT", "555")


def test_adapter_satisfies_supports_conditional_orders_protocol():
    """Vérification du typage structurel - BinanceFuturesAdapter doit
    satisfaire le Protocol sans en hériter explicitement."""
    from shared.futures_adapter import SupportsConditionalOrders

    adapter = BinanceFuturesAdapter()
    assert isinstance(adapter, SupportsConditionalOrders)


# --- Flux de liquidations (chantier de données Liquidation Cascade, 16/08/2026) ---


def test_parse_liquidation_message_matches_official_binance_example():
    """Exemple exact de la documentation Binance Open Platform
    ("Liquidation Order Streams"), en mode ws simple (message nu, sans
    enveloppe stream/data) - vérifié le 17/08/2026."""
    raw = (
        '{"e":"forceOrder","E":1568014460893,"o":{"s":"BTCUSDT","S":"SELL","o":"LIMIT",'
        '"f":"IOC","q":"0.014","p":"9910","ap":"9910","X":"FILLED","l":"0.014","z":"0.014",'
        '"T":1568014460893}}'
    )

    event = parse_liquidation_message(raw)

    assert event is not None
    assert event.exchange == "binance"
    assert event.symbol == "BTC/USDT"
    assert event.side == "sell"
    assert event.price == Decimal("9910")
    assert event.quantity == Decimal("0.014")
    assert event.notional == Decimal("9910") * Decimal("0.014")
    assert event.order_status == "FILLED"


def test_parse_liquidation_message_handles_stream_mode_envelope():
    """Mode `stream` (flux combinés, celui réellement utilisé par
    `stream_liquidations`) : le message est enveloppé
    `{"stream": "...", "data": {...}}` - vérifié contre la documentation
    Binance ("Combined stream events are wrapped as follows")."""
    raw = (
        '{"stream":"btcusdt@forceOrder","data":{"e":"forceOrder","E":1568014460893,'
        '"o":{"s":"BTCUSDT","S":"BUY","o":"LIMIT","f":"IOC","q":"1.5","p":"100",'
        '"ap":"100","X":"FILLED","l":"1.5","z":"1.5","T":1568014460893}}}'
    )

    event = parse_liquidation_message(raw)

    assert event is not None
    assert event.side == "buy"
    assert event.notional == Decimal("150")


def test_parse_liquidation_message_returns_none_on_invalid_json():
    assert parse_liquidation_message("not-json{{{") is None


def test_parse_liquidation_message_returns_none_on_missing_fields():
    assert parse_liquidation_message('{"e":"forceOrder"}') is None  # "o" absent


@pytest.mark.asyncio
async def test_stream_liquidations_connects_to_the_market_endpoint_not_the_legacy_one(monkeypatch):
    """Le point de vérification le plus important de ce chantier :
    `forceOrder` appartient à la catégorie "Market" (vérifié le
    17/08/2026, cf. docstring du module) - une connexion à l'ancienne URL
    `wss://fstream.binance.com/ws/...` (décommissionnée depuis le
    23/04/2026) ne recevrait plus aucune donnée, silencieusement."""
    adapter = BinanceFuturesAdapter()
    captured_urls = []

    class _FakeConnection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            return '{"stream":"btcusdt@forceOrder","data":{}}'  # un seul message, suffisant pour ce test

    def fake_connect(url, **kwargs):
        captured_urls.append(url)
        return _FakeConnection()

    import websockets

    monkeypatch.setattr(websockets, "connect", fake_connect)

    messages = []
    async for message in adapter.stream_liquidations(["btcusdt"]):
        messages.append(message)
        break  # un seul message suffit à vérifier l'URL de connexion

    assert captured_urls[0].startswith("wss://fstream.binance.com/market/")
    assert "btcusdt@forceOrder" in captured_urls[0]
