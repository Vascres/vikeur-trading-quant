"""Tests de l'adaptateur HTX (Phase 7).

Ces tests ne se connectent jamais au vrai WebSocket HTX - ils vérifient
la logique de parsing et de reconnexion en isolation, conformément à
l'exigence de la Phase 1 ("chaque module facilement testable").
"""

import gzip
import json

import pytest

from data_collector.adapters.htx import HTXAdapter


def test_decode_message_handles_gzip_bytes():
    payload = {"ch": "market.btcusdt.trade.detail", "tick": {"data": []}}
    compressed = gzip.compress(json.dumps(payload).encode("utf-8"))

    decoded = HTXAdapter._decode_message(compressed)

    assert decoded == payload


def test_decode_message_handles_plain_json_string():
    payload = {"ping": 12345}
    decoded = HTXAdapter._decode_message(json.dumps(payload))
    assert decoded == payload


def test_decode_message_returns_none_on_garbage():
    assert HTXAdapter._decode_message(b"\x00\x01not-gzip-not-json") is None


@pytest.mark.parametrize(
    "channel,expected_symbol",
    [
        ("market.btcusdt.trade.detail", "btcusdt"),
        ("market.ethusdt.depth.step0", "ethusdt"),
        ("", None),
        ("malformed", None),
    ],
)
def test_extract_symbol_from_channel(channel, expected_symbol):
    assert HTXAdapter._extract_symbol_from_channel(channel) == expected_symbol


@pytest.mark.asyncio
async def test_place_order_without_api_keys_raises_runtime_error():
    """Depuis la Phase 12, place_order est implémenté mais exige des clés API configurées."""
    adapter = HTXAdapter()
    with pytest.raises(RuntimeError, match="Clés API HTX non configurées"):
        await adapter.place_order("btcusdt", side="buy", quantity=1, price=None)
    await adapter.close()


@pytest.mark.asyncio
async def test_get_fee_rate_without_api_keys_raises_runtime_error():
    """ADR-0016 : get_fee_rate est un appel authentifié comme place_order/
    get_balances - mêmes garde-fous."""
    adapter = HTXAdapter()
    with pytest.raises(RuntimeError, match="Clés API HTX non configurées"):
        await adapter.get_fee_rate(["btcusdt"])
    await adapter.close()


@pytest.mark.asyncio
async def test_get_order_status_without_api_keys_raises_runtime_error():
    """get_order_status (Phase 20) exige aussi des clés API configurées."""
    adapter = HTXAdapter()
    with pytest.raises(RuntimeError, match="Clés API HTX non configurées"):
        await adapter.get_order_status("order-123")
    await adapter.close()


@pytest.mark.asyncio
async def test_journal_event_emitted_without_publisher_falls_back_to_log(caplog):
    """Sans journal_publisher injecté, l'événement doit au moins être loggé - jamais silencieux."""
    adapter = HTXAdapter(journal_publisher=None)
    with caplog.at_level("INFO"):
        adapter._emit_journal_event("collector.connected", {"exchange": "htx"})
    assert "collector.connected" in caplog.text
    await adapter.close()
