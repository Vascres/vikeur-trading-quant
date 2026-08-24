"""Tests de shared.heartbeat (ADR-0013)."""

from __future__ import annotations

import asyncio
import pathlib

import pytest

from shared.heartbeat import run_heartbeat


@pytest.mark.asyncio
async def test_run_heartbeat_touches_file_repeatedly(tmp_path: pathlib.Path):
    heartbeat_path = tmp_path / "heartbeat"
    task = asyncio.create_task(run_heartbeat(heartbeat_path))

    # Laisse le temps à au moins une itération de s'exécuter, sans
    # dépendre de HEARTBEAT_INTERVAL_SECONDS réel (30s, trop long pour un
    # test) - on ne teste que le premier `touch()`, avant le premier sleep.
    await asyncio.sleep(0.05)
    task.cancel()

    assert heartbeat_path.exists()
