"""Tests de data_collector.adapters.binance.BinanceAdapter (ADR-0012).

Miroir des tests existants pour HTXAdapter (test_execution_engine.py) -
même niveau de rigueur sur la signature et la conversion de symbole."""

from __future__ import annotations

import hashlib
import hmac
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlencode

import pytest

from data_collector.adapters.binance import BinanceAdapter
from shared.exchange_adapter import OrderSide


def test_sign_params_raises_without_api_keys():
    adapter = BinanceAdapter()
    with pytest.raises(RuntimeError, match="Clés API Binance non configurées"):
        adapter._sign_params({"symbol": "BTCUSDT"})


def test_sign_params_produces_verifiable_signature():
    adapter = BinanceAdapter(api_key="test-key", api_secret="test-secret")
    signed = adapter._sign_params({"symbol": "BTCUSDT"})

    assert "timestamp" in signed
    assert "signature" in signed

    unsigned = {k: v for k, v in signed.items() if k != "signature"}
    expected_signature = hmac.new(
        b"test-secret", urlencode(unsigned).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    assert signed["signature"] == expected_signature


def test_auth_headers_contains_api_key():
    adapter = BinanceAdapter(api_key="test-key", api_secret="test-secret")
    assert adapter._auth_headers() == {"X-MBX-APIKEY": "test-key"}


@pytest.mark.asyncio
async def test_place_order_converts_canonical_symbol_to_native():
    adapter = BinanceAdapter(api_key="test-key", api_secret="test-secret")

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {"orderId": 12345}
    adapter._http_client.post = AsyncMock(return_value=fake_response)

    await adapter.place_order(
        symbol="BTC/USDT", side=OrderSide.BUY, quantity=Decimal("0.01"), price=Decimal("60000")
    )

    _, kwargs = adapter._http_client.post.call_args
    assert kwargs["params"]["symbol"] == "BTCUSDT"
    assert kwargs["params"]["side"] == "BUY"


@pytest.mark.asyncio
async def test_get_order_status_translates_binance_vocabulary():
    adapter = BinanceAdapter(api_key="test-key", api_secret="test-secret")

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "status": "FILLED",
        "executedQty": "0.01",
        "cummulativeQuoteQty": "600.0",
    }
    adapter._http_client.get = AsyncMock(return_value=fake_response)

    status = await adapter.get_order_status("12345", symbol="BTC/USDT")

    assert status == {"state": "filled", "filled_amount": "0.01", "filled_cash_amount": "600.0"}


@pytest.mark.asyncio
async def test_get_order_status_requires_symbol():
    adapter = BinanceAdapter(api_key="test-key", api_secret="test-secret")
    with pytest.raises(ValueError, match="nécessite `symbol`"):
        await adapter.get_order_status("12345")


@pytest.mark.asyncio
async def test_cancel_order_requires_symbol():
    adapter = BinanceAdapter(api_key="test-key", api_secret="test-secret")
    with pytest.raises(ValueError, match="nécessite `symbol`"):
        await adapter.cancel_order("12345")


@pytest.mark.asyncio
async def test_get_balances_filters_zero_balances():
    adapter = BinanceAdapter(api_key="test-key", api_secret="test-secret")

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = {
        "balances": [
            {"asset": "USDT", "free": "500.0", "locked": "0"},
            {"asset": "ETH", "free": "0", "locked": "0"},
        ]
    }
    adapter._http_client.get = AsyncMock(return_value=fake_response)

    balances = await adapter.get_balances()

    assert balances == {"USDT": Decimal("500.0")}


# --- Chantier CostModel unique (16/08/2026) : get_fee_rate ---


@pytest.mark.asyncio
async def test_get_fee_rate_filters_response_to_requested_symbols():
    adapter = BinanceAdapter(api_key="test-key", api_secret="test-secret")

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = [
        {"symbol": "BTCUSDT", "makerCommission": "0.001000", "takerCommission": "0.001000"},
        {"symbol": "DOGEUSDT", "makerCommission": "0.001000", "takerCommission": "0.001000"},
    ]
    adapter._http_client.get = AsyncMock(return_value=fake_response)

    entries = await adapter.get_fee_rate(["BTCUSDT"])

    assert len(entries) == 1
    assert entries[0]["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_get_fee_rate_signs_the_request():
    adapter = BinanceAdapter(api_key="test-key", api_secret="test-secret")

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json.return_value = []
    adapter._http_client.get = AsyncMock(return_value=fake_response)

    await adapter.get_fee_rate(["BTCUSDT"])

    _, kwargs = adapter._http_client.get.call_args
    assert "signature" in kwargs["params"]
    assert kwargs["headers"] == {"X-MBX-APIKEY": "test-key"}


# --- Correctif du 19/08/2026 (disque VPS saturé deux nuits de suite,
# ~28 lignes/seconde mesurées en production sur le carnet d'ordres
# Binance) : depth20@100ms -> depth20@1000ms ---


@pytest.mark.asyncio
async def test_stream_order_book_uses_1000ms_update_speed_not_100ms():
    """Le cœur du correctif : vérifie le nom de flux RÉELLEMENT construit
    et transmis à `_stream_channels`, pas une supposition sur le code -
    aucun test ne couvrait cette méthode avant ce correctif, ce qui
    explique qu'elle ait pu tourner à 10x la fréquence utile pendant
    des jours sans être détectée."""

    async def fake_stream_channels(channels):
        # Capture les canaux réellement demandés, puis s'arrête -
        # jamais besoin d'un vrai WebSocket pour vérifier la construction
        # du nom de flux.
        fake_stream_channels.captured = channels
        return
        yield  # pragma: no cover - rend la fonction un générateur, jamais atteint

    adapter = BinanceAdapter()
    adapter._stream_channels = fake_stream_channels

    async for _ in adapter.stream_order_book(["BTCUSDT", "ETHUSDT"]):
        pass  # jamais de message émis par le faux flux ci-dessus

    assert fake_stream_channels.captured == ["btcusdt@depth20@1000ms", "ethusdt@depth20@1000ms"]
    for channel in fake_stream_channels.captured:
        assert "@100ms" not in channel, f"Régression : {channel} est repassé à la fréquence rapide."
