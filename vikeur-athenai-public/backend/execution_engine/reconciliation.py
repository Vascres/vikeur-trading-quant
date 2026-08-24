"""Reconstruction d'état au démarrage (Phase 5, §3.2).

Avant de reprendre toute nouvelle décision après un redémarrage
(déploiement, crash), le moteur d'exécution doit connaître l'état exact
des positions ouvertes et des ordres en attente - jamais repartir "à
l'aveugle" alors que du capital réel peut être engagé.
"""

import asyncpg


async def reconcile_open_positions(db_pool: asyncpg.Pool) -> list[dict]:
    """Retourne la liste des positions actuellement ouvertes, par symbole.

    Fonction volontairement simple en V1 : elle lit l'état connu de la
    base. Une vérification croisée avec le solde réel de l'exchange
    (pour détecter une désynchronisation) est une amélioration prévue
    avant la mise en production (Phase 20), pas bloquante pour la V1
    tant que le mode réel n'est pas activé.
    """
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, exchange, symbol, execution_mode, entry_price, quantity, opened_at
            FROM positions
            WHERE status = 'open';
            """
        )
    return [dict(row) for row in rows]


async def reconcile_pending_orders(db_pool: asyncpg.Pool) -> list[dict]:
    """Retourne les ordres restés 'pending' - potentiellement orphelins après un crash."""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, exchange, symbol, side, execution_mode, requested_quantity, created_at
            FROM orders
            WHERE status = 'pending';
            """
        )
    return [dict(row) for row in rows]
