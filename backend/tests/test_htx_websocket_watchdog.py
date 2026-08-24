"""Tests de HTXAdapter._stream_channels - correctif du 14/08/2026.

Bug découvert en production : `ping_interval=None` désactive la
surveillance de connexion de `websockets` - une connexion à moitié
morte (aucune trame de fermeture jamais reçue) restait indéfiniment
silencieuse, sans erreur, sans reconnexion. `PING_TIMEOUT_SECONDS`
existait déjà dans le module mais n'était jamais branché - conséquence
réelle observée : 3 jours de collecte figée (11 au 14 août 2026),
totalement invisible jusqu'à investigation manuelle.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import data_collector.adapters.htx as htx_module
from data_collector.adapters.htx import HTXAdapter


class _FakeWebSocket:
    """Simule une connexion WS : `recv_side_effects` est une liste de
    callables (chacun awaité pour produire le prochain `recv()`) - permet
    de mélanger messages normaux, silence prolongé (timeout réel) et
    déconnexion, exactement comme un vrai flux HTX."""

    def __init__(self, recv_side_effects: list) -> None:
        self._effects = list(recv_side_effects)
        self.sent_messages: list[str] = []

    async def recv(self):
        effect = self._effects.pop(0)
        return await effect()

    async def send(self, payload: str) -> None:
        self.sent_messages.append(payload)


def _instant(value):
    async def _effect():
        return value

    return _effect


def _hang_longer_than(seconds: float):
    """Simule un silence prolongé - `recv()` ne revient qu'après `seconds`,
    plus long que le timeout testé, pour déclencher un vrai `TimeoutError`
    via `asyncio.wait_for` (pas un mock du timeout - le mécanisme réel)."""

    async def _effect():
        await asyncio.sleep(seconds)
        return json.dumps({"unreachable": True})

    return _effect


async def _collect_n(async_gen, n: int) -> list:
    results = []
    async for item in async_gen:
        results.append(item)
        if len(results) >= n:
            break
    return results


def _patch_websocket_connect(monkeypatch, fake_ws_sequence: list[_FakeWebSocket]):
    """Chaque appel successif à `websockets.connect(...)` retourne le
    prochain faux WS de la séquence - simule des reconnexions successives.
    Non utilisé directement par tous les tests (certains construisent leur
    propre gestionnaire de contexte inline pour varier le comportement par
    appel), conservé car réutilisable pour de futurs tests de ce module."""
    remaining = list(fake_ws_sequence)

    class _FakeConnectCM:
        async def __aenter__(self):
            return remaining.pop(0)

        async def __aexit__(self, *exc_info):
            return False

    def _fake_connect(*args, **kwargs):
        return _FakeConnectCM()

    monkeypatch.setattr(htx_module.websockets, "connect", _fake_connect)


@pytest.mark.asyncio
async def test_yields_decoded_trade_messages():
    trade_payload = json.dumps({"ch": "market.btcusdt.trade.detail", "tick": {"price": "60000"}})
    ws = _FakeWebSocket([_instant(trade_payload), _hang_longer_than(999)])

    class _CM:
        async def __aenter__(self):
            return ws

        async def __aexit__(self, *a):
            return False

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(htx_module.websockets, "connect", lambda *a, **k: _CM())
        adapter = HTXAdapter()
        gen = adapter._stream_channels(["market.btcusdt.trade.detail"])
        results = await _collect_n(gen, 1)

    assert results[0]["ch"] == "market.btcusdt.trade.detail"


@pytest.mark.asyncio
async def test_responds_to_htx_ping_without_yielding_it():
    ping_payload = json.dumps({"ping": 1234567890})
    trade_payload = json.dumps({"ch": "market.btcusdt.trade.detail", "tick": {}})
    ws = _FakeWebSocket([_instant(ping_payload), _instant(trade_payload)])

    class _CM:
        async def __aenter__(self):
            return ws

        async def __aexit__(self, *a):
            return False

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(htx_module.websockets, "connect", lambda *a, **k: _CM())
        adapter = HTXAdapter()
        gen = adapter._stream_channels(["market.btcusdt.trade.detail"])
        results = await _collect_n(gen, 1)

    # Le ping n'est jamais transmis à l'appelant, seulement le trade qui suit.
    assert results == [{"ch": "market.btcusdt.trade.detail", "tick": {}}]
    # Un pong a bien été renvoyé en réponse au ping.
    assert any(json.loads(m).get("pong") == 1234567890 for m in ws.sent_messages)


@pytest.mark.asyncio
async def test_forces_reconnection_after_prolonged_silence(monkeypatch):
    """Le cœur du correctif : un silence plus long que PING_TIMEOUT_SECONDS
    doit déclencher une reconnexion réelle - pas rester bloqué indéfiniment
    comme avant (bug ayant causé 3 jours de collecte figée)."""
    monkeypatch.setattr(htx_module, "PING_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(htx_module, "INITIAL_BACKOFF_SECONDS", 0.01)
    monkeypatch.setattr(htx_module, "MAX_BACKOFF_SECONDS", 0.01)

    trade_after_reconnect = json.dumps({"ch": "market.btcusdt.trade.detail", "tick": {"price": "1"}})

    # Premier WS : silence prolongé (bien plus long que le timeout de 0.05s) -> doit forcer la sortie.
    ws_1 = _FakeWebSocket([_hang_longer_than(1.0)])
    # Deuxième WS (après reconnexion) : un vrai message.
    ws_2 = _FakeWebSocket([_instant(trade_after_reconnect), _hang_longer_than(999)])

    connect_call_count = {"n": 0}

    class _CM:
        def __init__(self, ws):
            self._ws = ws

        async def __aenter__(self):
            return self._ws

        async def __aexit__(self, *a):
            return False

    def fake_connect(*a, **k):
        connect_call_count["n"] += 1
        return _CM(ws_1 if connect_call_count["n"] == 1 else ws_2)

    monkeypatch.setattr(htx_module.websockets, "connect", fake_connect)

    events = []
    adapter = HTXAdapter(journal_publisher=lambda t, p: events.append((t, p)))
    gen = adapter._stream_channels(["market.btcusdt.trade.detail"])

    results = await asyncio.wait_for(_collect_n(gen, 1), timeout=5)

    assert results[0]["tick"]["price"] == "1"
    assert connect_call_count["n"] == 2  # une vraie reconnexion a bien eu lieu
    assert any(t == "collector.stale_connection" for t, _ in events)


@pytest.mark.asyncio
async def test_stale_connection_event_reports_the_configured_timeout(monkeypatch):
    monkeypatch.setattr(htx_module, "PING_TIMEOUT_SECONDS", 0.03)
    monkeypatch.setattr(htx_module, "INITIAL_BACKOFF_SECONDS", 0.01)
    monkeypatch.setattr(htx_module, "MAX_BACKOFF_SECONDS", 0.01)

    ws_1 = _FakeWebSocket([_hang_longer_than(1.0)])
    ws_2 = _FakeWebSocket([_instant(json.dumps({"ch": "x", "tick": {}})), _hang_longer_than(999)])
    calls = {"n": 0}

    class _CM:
        def __init__(self, ws):
            self._ws = ws

        async def __aenter__(self):
            return self._ws

        async def __aexit__(self, *a):
            return False

    def fake_connect(*a, **k):
        calls["n"] += 1
        return _CM(ws_1 if calls["n"] == 1 else ws_2)

    monkeypatch.setattr(htx_module.websockets, "connect", fake_connect)

    events = []
    adapter = HTXAdapter(journal_publisher=lambda t, p: events.append((t, p)))
    gen = adapter._stream_channels(["x"])
    await asyncio.wait_for(_collect_n(gen, 1), timeout=5)

    stale_events = [p for t, p in events if t == "collector.stale_connection"]
    assert stale_events
    assert stale_events[0]["silence_seconds"] == 0.03
