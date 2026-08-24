"""Source de vérité du mode d'exécution courant (ADR-0004, ADR-0008).

`execution_mode_state` remplace la variable d'environnement
`EXECUTION_MODE` : le mode courant est toujours la ligne la plus
récente de cette table (historique complet conservé, jamais de mutation
- cf. Data Governance Spec §4). Toute lecture du mode courant, où
qu'elle ait lieu dans le backend, passe par ce module - jamais par un
nouvel appel direct à `os.environ`.
"""

from __future__ import annotations

import asyncpg


async def fetch_current_mode(conn: asyncpg.Connection) -> str:
    """Version pour appelant disposant déjà d'une connexion ouverte
    (évite une acquisition de pool imbriquée) - utilisée par les modules
    qui lisent le mode à l'intérieur d'un `async with db_pool.acquire()`
    déjà en cours (risk_engine, portfolio)."""
    row = await conn.fetchrow("SELECT mode FROM execution_mode_state ORDER BY changed_at DESC LIMIT 1;")
    if row is None:
        raise RuntimeError(
            "execution_mode_state est vide - aucun mode d'exécution initialisé. "
            "La migration 0010 doit avoir semé un état initial ; si ce n'est pas "
            "le cas, le système ne peut fonctionner en toute sécurité (principe "
            "directeur 3 : jamais d'hypothèse par défaut sur un état inconnu)."
        )
    return row["mode"]


async def get_current_mode(db_pool: asyncpg.Pool) -> str:
    """Version autonome pour un appelant qui n'a pas de connexion ouverte
    (ex. execution_engine.factory, route API)."""
    async with db_pool.acquire() as conn:
        return await fetch_current_mode(conn)
