"""Tests de data_collector.adapters.htx_futures.HTXFuturesAdapter (ADR-0018).

Même niveau de couverture que test_htx_adapter.py pour l'adaptateur spot :
les garde-fous d'authentification et la logique pure (mapping de
symbole), pas les appels réseau réels."""

from __future__ import annotations

from decimal import Decimal

import pytest

from data_collector.adapters.htx_futures import HTXFuturesAdapter
from shared.futures_adapter import PositionSide


@pytest.mark.asyncio
async def test_place_order_without_api_keys_raises_runtime_error():
    adapter = HTXFuturesAdapter()
    with pytest.raises(RuntimeError, match="Clés API HTX Futures non configurées"):
        await adapter.place_order("BTC/USDT", PositionSide.LONG, Decimal("0.01"))
    await adapter.close()


@pytest.mark.asyncio
async def test_close_position_without_api_keys_raises_runtime_error():
    adapter = HTXFuturesAdapter()
    with pytest.raises(RuntimeError, match="Clés API HTX Futures non configurées"):
        await adapter.close_position("BTC/USDT", PositionSide.LONG, Decimal("0.01"))
    await adapter.close()


@pytest.mark.asyncio
async def test_get_positions_without_api_keys_raises_runtime_error():
    adapter = HTXFuturesAdapter()
    with pytest.raises(RuntimeError, match="Clés API HTX Futures non configurées"):
        await adapter.get_positions("BTC/USDT")
    await adapter.close()


@pytest.mark.asyncio
async def test_get_funding_rate_parses_real_measurement(monkeypatch):
    """ADR-0020 : mesure réelle, remplace le refus explicite laissé par
    ADR-0018 §3.4. Endpoint public - aucune clé API nécessaire."""
    adapter = HTXFuturesAdapter()

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "ok", "data": {"contract_code": "BTC-USDT", "funding_rate": "0.000123"}}

    captured_calls = []

    async def fake_get(path, params=None):
        captured_calls.append((path, params))
        return _FakeResponse()

    monkeypatch.setattr(adapter._http_client, "get", fake_get)

    rate = await adapter.get_funding_rate("BTC/USDT")

    assert rate == Decimal("0.000123")
    assert captured_calls == [("/linear-swap-api/v1/swap_funding_rate", {"contract_code": "BTC-USDT"})]
    await adapter.close()


@pytest.mark.asyncio
async def test_get_funding_rate_raises_explicitly_on_error_status(monkeypatch):
    """Jamais une valeur inventée si HTX répond une erreur (ADR-0020,
    même principe que le refus explicite qu'il remplace)."""
    adapter = HTXFuturesAdapter()

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "error", "err_msg": "symbole introuvable"}

    async def fake_get(path, params=None):
        return _FakeResponse()

    monkeypatch.setattr(adapter._http_client, "get", fake_get)

    with pytest.raises(RuntimeError, match="Impossible de récupérer le funding"):
        await adapter.get_funding_rate("BTC/USDT")
    await adapter.close()


def test_contract_code_mapping():
    adapter = HTXFuturesAdapter()
    assert adapter._contract_code("BTC/USDT") == "BTC-USDT"
    assert adapter._contract_code("ETH/USDT") == "ETH-USDT"
