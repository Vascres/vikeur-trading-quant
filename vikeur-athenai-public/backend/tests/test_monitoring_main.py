"""Tests de monitoring.main (correctif du 16/08/2026 - consolidation de
l'alerting via le pipeline notifications, découvert en documentant le projet).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from monitoring.health_checks import Alert
from monitoring.main import MODULE_FRESHNESS_THRESHOLDS, _run_all_checks, _send_if_not_in_cooldown


@pytest.mark.asyncio
async def test_sends_and_sets_cooldown_when_not_already_sent():
    redis_client = AsyncMock()
    redis_client.get.return_value = None
    events = []
    alert = Alert(check_name="disk_space", message="Espace disque à 95%.")

    await _send_if_not_in_cooldown(redis_client, alert, lambda t, p: events.append((t, p)))

    assert events == [
        ("monitoring.alert_triggered", {"check_name": "disk_space", "message": "Espace disque à 95%."})
    ]
    redis_client.set.assert_awaited_once()


@pytest.mark.asyncio
async def test_skips_publishing_when_already_in_cooldown():
    redis_client = AsyncMock()
    redis_client.get.return_value = b"1"
    events = []
    alert = Alert(check_name="disk_space", message="Espace disque à 95%.")

    await _send_if_not_in_cooldown(redis_client, alert, lambda t, p: events.append((t, p)))

    assert events == []
    redis_client.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_all_checks_publishes_kill_switch_alert_when_active():
    conn = AsyncMock()
    # Une valeur None par module suivi (aucune fraîcheur connue), puis 0 pour le décompte de reconnexions.
    conn.fetchval.side_effect = [None] * len(MODULE_FRESHNESS_THRESHOLDS) + [0]
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    redis_client = AsyncMock()
    redis_client.get.side_effect = lambda key: b"1" if key == "risk:kill_switch" else None

    events = []
    await _run_all_checks(pool, redis_client, lambda t, p: events.append((t, p)))

    check_names = {p["check_name"] for _t, p in events}
    assert "kill_switch" in check_names
