"""Suivi réel des positions (Phase 15, §5 ; ADR-0019 ; étendu Étapes 7-9
du 16/08/2026 - marge/levier/triptyque d'ordres).

Appelé après chaque remplissage par les modes d'exécution qui écrivent
dans la table live `positions` (Phase 6) - contrairement au backtest
(Phase 14) qui gère son état en mémoire (BacktestPortfolio) sans jamais
toucher cette table.

Règle V1 spot (long-only, Phase 15 §3, inchangée par ADR-0019) : une
vente clôture TOUJOURS la totalité de la position ouverte correspondante.

ADR-0019 (futures) : un symbole peut désormais porter deux positions
simultanées et indépendantes sur le même exchange - une spot (toujours
longue) et une futures (longue OU courte, `position_side`) - jamais
mélangées (la requête d'existence est filtrée par `market_type`).
Même simplification V1 que le spot : un remplissage de sens opposé à la
position futures existante la clôture entièrement, jamais un renversement
partiel en une seule opération.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import asyncpg


@dataclass(frozen=True)
class FuturesFillResult:
    """Retourné uniquement pour `market_type='futures_perpetual'` (le
    spot garde un retour `None`, comportement inchangé pour tout
    appelant existant) - porte l'information dont
    `execution_engine/modes/real.py` a besoin pour orchestrer le
    triptyque d'ordres (Étape 9, 16/08/2026) sans que `apply_fill`
    n'ait lui-même à connaître l'adaptateur exchange (séparation
    DB/réseau préservée)."""

    position_id: int
    opened: bool  # nouvelle position -> poser un stop-loss automatique
    closed: bool  # position clôturée -> annuler tout ordre conditionnel restant
    previous_stop_loss_order_id: str | None = None
    previous_take_profit_order_id: str | None = None


async def apply_fill(
    db_pool: asyncpg.Pool,
    *,
    exchange: str,
    symbol: str,
    execution_mode: str,
    side: str,
    filled_price: Decimal,
    filled_quantity: Decimal,
    decision_id: int | None = None,
    publish_journal_event=None,
    market_type: str = "spot",
    leverage: int | None = None,
    margin_used: Decimal | None = None,
    liquidation_price_reference: Decimal | None = None,
) -> FuturesFillResult | None:
    if market_type == "futures_perpetual":
        return await _apply_futures_fill(
            db_pool,
            exchange=exchange,
            symbol=symbol,
            execution_mode=execution_mode,
            side=side,
            filled_price=filled_price,
            filled_quantity=filled_quantity,
            decision_id=decision_id,
            publish_journal_event=publish_journal_event,
            leverage=leverage,
            margin_used=margin_used,
            liquidation_price_reference=liquidation_price_reference,
        )

    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow(
            """
            SELECT id, entry_price, quantity FROM positions
            WHERE status = 'open' AND exchange = $1 AND symbol = $2 AND execution_mode = $3
                  AND market_type = 'spot';
            """,
            exchange,
            symbol,
            execution_mode,
        )

        if side == "buy":
            if existing is None:
                await conn.execute(
                    """
                    INSERT INTO positions
                        (exchange, symbol, execution_mode, opened_at, entry_price, quantity,
                         status, decision_id, market_type)
                    VALUES ($1, $2, $3, $4, $5, $6, 'open', $7, 'spot');
                    """,
                    exchange,
                    symbol,
                    execution_mode,
                    datetime.now(tz=UTC),
                    filled_price,
                    filled_quantity,
                    decision_id,
                )
                return

            existing_quantity = Decimal(str(existing["quantity"]))
            existing_price = Decimal(str(existing["entry_price"]))
            total_quantity = existing_quantity + filled_quantity
            weighted_price = (
                existing_price * existing_quantity + filled_price * filled_quantity
            ) / total_quantity

            await conn.execute(
                "UPDATE positions SET entry_price = $1, quantity = $2 WHERE id = $3;",
                weighted_price,
                total_quantity,
                existing["id"],
            )
            return

        # side == "sell" : clôture entière (Phase 15, §3)
        if existing is None:
            # Ne devrait jamais arriver grâce à SpotNoShortingRule (Phase 15, §4) -
            # seconde ligne de défense, jamais silencieuse.
            if publish_journal_event:
                publish_journal_event(
                    "execution_engine.sell_without_position",
                    {"exchange": exchange, "symbol": symbol, "execution_mode": execution_mode},
                )
            return

        existing_quantity = Decimal(str(existing["quantity"]))
        existing_price = Decimal(str(existing["entry_price"]))
        realized_pnl = (filled_price - existing_price) * existing_quantity

        await conn.execute(
            """
            UPDATE positions
            SET status = 'closed', exit_price = $1, realized_pnl = $2, closed_at = $3
            WHERE id = $4;
            """,
            filled_price,
            realized_pnl,
            datetime.now(tz=UTC),
            existing["id"],
        )


async def _apply_futures_fill(
    db_pool: asyncpg.Pool,
    *,
    exchange: str,
    symbol: str,
    execution_mode: str,
    side: str,
    filled_price: Decimal,
    filled_quantity: Decimal,
    decision_id: int | None,
    publish_journal_event,
    leverage: int | None,
    margin_used: Decimal | None,
    liquidation_price_reference: Decimal | None,
) -> FuturesFillResult:
    """ADR-0019 : contrairement au spot, une vente ouvre légitimement une
    position (courte) quand aucune n'existe - jamais un no-op journalisé
    comme `sell_without_position` (Phase 15 §4), qui ne s'applique qu'au
    spot (`SpotNoShortingRule`, gardée par `market_type` depuis ADR-0018)."""
    desired_side = "long" if side == "buy" else "short"

    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow(
            """
            SELECT id, entry_price, quantity, position_side, stop_loss_order_id, take_profit_order_id
            FROM positions
            WHERE status = 'open' AND exchange = $1 AND symbol = $2 AND execution_mode = $3
                  AND market_type = 'futures_perpetual';
            """,
            exchange,
            symbol,
            execution_mode,
        )

        if existing is None:
            position_id = await conn.fetchval(
                """
                INSERT INTO positions
                    (exchange, symbol, execution_mode, opened_at, entry_price, quantity,
                     status, decision_id, market_type, position_side,
                     leverage, margin_used, liquidation_price_reference)
                VALUES ($1, $2, $3, $4, $5, $6, 'open', $7, 'futures_perpetual', $8, $9, $10, $11)
                RETURNING id;
                """,
                exchange,
                symbol,
                execution_mode,
                datetime.now(tz=UTC),
                filled_price,
                filled_quantity,
                decision_id,
                desired_side,
                leverage,
                margin_used,
                liquidation_price_reference,
            )
            return FuturesFillResult(position_id=position_id, opened=True, closed=False)

        existing_quantity = Decimal(str(existing["quantity"]))
        existing_price = Decimal(str(existing["entry_price"]))

        if existing["position_side"] == desired_side:
            # Renforce la position existante (même sens) - moyenne pondérée, comme le spot.
            total_quantity = existing_quantity + filled_quantity
            weighted_price = (
                existing_price * existing_quantity + filled_price * filled_quantity
            ) / total_quantity
            await conn.execute(
                "UPDATE positions SET entry_price = $1, quantity = $2 WHERE id = $3;",
                weighted_price,
                total_quantity,
                existing["id"],
            )
            return FuturesFillResult(position_id=existing["id"], opened=False, closed=False)

        # Sens opposé à la position existante : clôture entière (même
        # simplification V1 que le spot, Phase 15 §3) - jamais un
        # renversement partiel en une seule opération.
        if existing["position_side"] == "long":
            realized_pnl = (filled_price - existing_price) * existing_quantity
        else:  # short : le profit vient d'une baisse du prix
            realized_pnl = (existing_price - filled_price) * existing_quantity

        await conn.execute(
            """
            UPDATE positions
            SET status = 'closed', exit_price = $1, realized_pnl = $2, closed_at = $3
            WHERE id = $4;
            """,
            filled_price,
            realized_pnl,
            datetime.now(tz=UTC),
            existing["id"],
        )
        return FuturesFillResult(
            position_id=existing["id"],
            opened=False,
            closed=True,
            previous_stop_loss_order_id=existing["stop_loss_order_id"],
            previous_take_profit_order_id=existing["take_profit_order_id"],
        )


async def record_conditional_order_ids(
    db_pool: asyncpg.Pool,
    position_id: int,
    *,
    stop_loss_order_id: str | None = None,
    take_profit_order_id: str | None = None,
) -> None:
    """Enregistre les identifiants d'ordres conditionnels posés par le
    triptyque (Étape 9, 16/08/2026) - appelé par `execution_engine/modes/
    real.py` juste après `place_stop_loss`/`place_take_profit`, jamais
    au moment de l'ouverture elle-même (ces ordres sont posés APRÈS que
    l'entrée soit confirmée remplie, cf. limitation d'atomicité
    documentée dans `data_collector/adapters/binance_futures.py`)."""
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE positions
            SET stop_loss_order_id = COALESCE($1, stop_loss_order_id),
                take_profit_order_id = COALESCE($2, take_profit_order_id)
            WHERE id = $3;
            """,
            stop_loss_order_id,
            take_profit_order_id,
            position_id,
        )
