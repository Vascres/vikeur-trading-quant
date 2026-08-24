"""Heartbeat partagé pour un HEALTHCHECK Docker significatif (ADR-0013).

Les services sans serveur HTTP (`engine`, `monitoring`, `backup`,
`portfolio`, `calibration`) partagent la même image que `backend`, dont
le `HEALTHCHECK` teste `http://localhost:8000/health` - une route qui
n'existe que dans `backend` (FastAPI/uvicorn). Ces services étaient donc
marqués "unhealthy" en permanence, quel que soit leur état réel (bug
préexistant, découvert en déployant pour de vrai).

Ce heartbeat tourne sur son propre intervalle, indépendant du cycle
métier de chaque service - il prouve que la boucle asyncio est vivante
et réactive (détecte un blocage/deadlock), pas que le dernier cycle
métier a réussi (ce que les événements déjà publiés dans `events_journal`
couvrent séparément).
"""

from __future__ import annotations

import asyncio
import pathlib

HEARTBEAT_PATH = pathlib.Path("/tmp/heartbeat")
HEARTBEAT_INTERVAL_SECONDS = 30


async def run_heartbeat(path: pathlib.Path = HEARTBEAT_PATH) -> None:
    """À lancer une fois via `asyncio.create_task(run_heartbeat())` au
    démarrage de chaque service en boucle - ne retourne jamais."""
    while True:
        path.touch()
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
