"""Porte de gouvernance dédiée au futures réel (ADR-0018 §3.3).

Délibérément séparée de `evaluate_prerequisites` (mode réel spot,
ADR-0004/0008) - le futures introduit des risques que le spot n'a pas
(funding, surface d'API distincte) et ne doit jamais être débloqué
automatiquement en même temps que le mode réel spot. Réutilise la table
`governance_attestations`, déjà générique (`key` libre) - aucune
migration de schéma nécessaire pour ce point.
"""

from __future__ import annotations

import asyncpg

FUTURES_REAL_TRADING_KEY = "futures_real_trading_enabled"


async def is_futures_real_trading_enabled(db_pool: asyncpg.Pool) -> bool:
    """Retourne `True` uniquement si une attestation `futures_real_trading_enabled`
    a été explicitement enregistrée - jamais par défaut, jamais déduite du
    mode réel spot déjà actif (ADR-0018 §3.3)."""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM governance_attestations WHERE key = $1 LIMIT 1;",
            FUTURES_REAL_TRADING_KEY,
        )
    return row is not None
