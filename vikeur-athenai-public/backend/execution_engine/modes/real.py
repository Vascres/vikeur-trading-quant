"""Mode Réel (Phase 12, §4 ; complété en Phase 20, §3 ; ADR-0019 futures ;
étendu Étape 9 du 16/08/2026 - triptyque d'ordres).

Seul mode qui contacte réellement l'exchange. Appelle
ExchangeAdapter.place_order, puis confirme le remplissage par polling
(get_order_status, Phase 20) avant de mettre à jour `positions`
(execution_engine/positions.py, Phase 15) - fermait un manque signalé
depuis la Phase 12, §6.

ADR-0019 : pour `market_type='futures_perpetual'`, vérifie
explicitement l'attestation `futures_real_trading_enabled`
(`execution_mode_governance/futures_gate.py`, ADR-0018) avant tout appel
à l'adaptateur futures - la dernière ligne de défense, au plus près de
l'endroit où l'argent réel serait engagé, jamais une vérification qu'on
pourrait oublier de rappeler ailleurs dans le pipeline.

Étape 9 (16/08/2026) : toute position futures fraîchement ouverte
reçoit immédiatement une tentative de stop-loss automatique
(`_attach_stop_loss`) au prix calculé par
`shared.futures_margin.compute_max_loss_stop_price` - JAMAIS atomique
avec l'entrée (Binance ne le permet pas, vérifié contre sa
documentation), donc une fenêtre existe où la position est ouverte sans
protection. Cette fenêtre est signalée bruyamment en cas d'échec
(`execution_engine.futures_stop_loss_placement_failed`), jamais
silencieuse - à surveiller côté Telegram une fois ce chantier construit.
Symétriquement, toute clôture annule les ordres conditionnels restants
(`_cancel_dangling_conditional_orders`), pour ne jamais laisser un stop
ou un take-profit orphelin sur l'exchange.
"""

import asyncio
import logging
from decimal import Decimal

import asyncpg

from execution_engine.common import insert_order_row
from execution_engine.positions import apply_fill, record_conditional_order_ids
from execution_mode_governance.futures_gate import is_futures_real_trading_enabled
from shared.exchange_adapter import ExchangeAdapter, OrderSide
from shared.execution_mode import ExecutionMode, OrderResult
from shared.futures_adapter import FuturesExchangeAdapter, PositionSide, SupportsConditionalOrders
from shared.futures_margin import (
    ACTUAL_LEVERAGE,
    MAX_LOSS_FRACTION_OF_MARGIN,
    compute_liquidation_price,
    compute_max_loss_stop_price,
    compute_required_margin,
)

logger = logging.getLogger(__name__)

FILL_POLL_ATTEMPTS = 5
FILL_POLL_INTERVAL_SECONDS = 2


class RealExecutionMode(ExecutionMode):
    mode_name = "real"

    def __init__(
        self,
        db_pool: asyncpg.Pool,
        exchange_adapters: dict[str, ExchangeAdapter],
        futures_exchange_adapters: dict[str, FuturesExchangeAdapter] | None = None,
        publish_journal_event=None,
    ) -> None:
        """`exchange_adapters` : un adaptateur par exchange actif
        (ADR-0012) - une décision porte toujours son `exchange` d'origine
        (`decisions.exchange`), ce mode doit donc pouvoir en servir
        plusieurs, jamais un seul figé à la construction.

        `futures_exchange_adapters` (ADR-0019) : parallèle et
        indépendant du dictionnaire spot - `None`/vide tant que le
        futures n'est déployé sur aucun exchange, jamais requis pour
        que le spot continue de fonctionner.

        `publish_journal_event` (Étape 9, 16/08/2026) : optionnel pour
        rester rétrocompatible avec tout appelant existant qui ne le
        fournirait pas encore (logue localement dans ce cas plutôt que
        d'échouer) - utilisé pour signaler bruyamment tout écart du
        triptyque d'ordres (stop-loss non posé, annulation échouée) :
        jamais une position réelle sans filet de sécurité signalée
        silencieusement."""
        self._db_pool = db_pool
        self._exchange_adapters = exchange_adapters
        self._futures_exchange_adapters = futures_exchange_adapters or {}
        self._publish_journal_event = publish_journal_event or (
            lambda event_type, payload: logger.warning("%s: %s", event_type, payload)
        )

    def _adapter_for(self, exchange: str) -> ExchangeAdapter:
        try:
            return self._exchange_adapters[exchange]
        except KeyError as exc:
            raise ValueError(
                f"Aucun adaptateur configuré pour l'exchange '{exchange}' en mode réel "
                f"(configurés : {list(self._exchange_adapters)})."
            ) from exc

    def _futures_adapter_for(self, exchange: str) -> FuturesExchangeAdapter:
        try:
            return self._futures_exchange_adapters[exchange]
        except KeyError as exc:
            raise ValueError(
                f"Aucun adaptateur futures configuré pour l'exchange '{exchange}' "
                f"(configurés : {list(self._futures_exchange_adapters)}, ADR-0019)."
            ) from exc

    async def execute(
        self,
        risk_check_id: int,
        decision_id: int,
        exchange: str,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal | None = None,
        market_type: str = "spot",
    ) -> OrderResult:
        if market_type == "futures_perpetual":
            return await self._execute_futures(
                risk_check_id, decision_id, exchange, symbol, side, quantity, price
            )
        return await self._execute_spot(risk_check_id, decision_id, exchange, symbol, side, quantity, price)

    async def _execute_spot(
        self, risk_check_id, decision_id, exchange, symbol, side, quantity, price
    ) -> OrderResult:
        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
        adapter = self._adapter_for(exchange)

        status = "pending"
        exchange_order_id = ""
        filled_price = None
        filled_quantity = None
        slippage = None

        try:
            exchange_order_id = await adapter.place_order(
                symbol=symbol, side=order_side, quantity=quantity, price=price
            )

            status, filled_quantity = await self._poll_fill_confirmation(adapter, exchange_order_id)

            if status == "filled" and filled_quantity is not None:
                # Le prix moyen réel de remplissage nécessiterait le détail
                # des transactions (endpoint /v1/order/orders/{id}/matchresults,
                # non implémenté ici) - approximation par le prix demandé,
                # limitation assumée et documentée (Phase 20, §3).
                filled_price = price
                await apply_fill(
                    self._db_pool,
                    exchange=exchange,
                    symbol=symbol,
                    execution_mode=self.mode_name,
                    side=side,
                    filled_price=filled_price,
                    filled_quantity=filled_quantity,
                    decision_id=decision_id,
                    market_type="spot",
                )
        except Exception:
            status = "rejected"
            raise  # l'appelant (Moteur de risque/orchestrateur) doit être informé de l'échec
        finally:
            await insert_order_row(
                self._db_pool,
                risk_check_id=risk_check_id,
                exchange=exchange,
                symbol=symbol,
                side=side,
                execution_mode=self.mode_name,
                requested_price=price,
                requested_quantity=quantity,
                filled_price=filled_price,
                filled_quantity=filled_quantity,
                slippage=slippage,
                status=status,
            )

        return OrderResult(
            order_id=exchange_order_id,
            status=status,
            filled_price=filled_price,
            filled_quantity=filled_quantity,
            slippage=slippage,
        )

    async def _execute_futures(
        self, risk_check_id, decision_id, exchange, symbol, side, quantity, price
    ) -> OrderResult:
        # ADR-0019 §4 : la dernière ligne de défense, jamais contournable -
        # aucun ordre futures réel sans cette attestation explicite,
        # indépendante du mode réel spot déjà actif.
        if not await is_futures_real_trading_enabled(self._db_pool):
            status = "rejected"
            await insert_order_row(
                self._db_pool,
                risk_check_id=risk_check_id,
                exchange=exchange,
                symbol=symbol,
                side=side,
                execution_mode=self.mode_name,
                requested_price=price,
                requested_quantity=quantity,
                filled_price=None,
                filled_quantity=None,
                slippage=None,
                status=status,
            )
            raise RuntimeError(
                "Ordre futures réel refusé : attestation 'futures_real_trading_enabled' absente "
                "(ADR-0018 §3.3, ADR-0019 §4) - jamais engagée automatiquement avec le mode réel spot."
            )

        position_side = PositionSide.LONG if side == "buy" else PositionSide.SHORT
        adapter = self._futures_adapter_for(exchange)

        status = "pending"
        exchange_order_id = ""
        filled_price = None
        filled_quantity = None
        slippage = None

        try:
            exchange_order_id = await adapter.place_order(
                symbol=symbol, side=position_side, quantity=quantity
            )

            # Limitation assumée, identique en esprit à celle du spot
            # (Phase 20 §3) : pas de polling de confirmation dédié pour le
            # futures dans cette première intégration (ADR-0019) - un
            # ordre marché HTX futures accepté est traité comme rempli au
            # prix demandé. À affiner (confirmation réelle du
            # remplissage) avant toute activation réelle.
            status = "filled"
            filled_quantity = quantity
            filled_price = price

            # --- Triptyque d'ordres (mandat §8-9, Étape 9, 16/08/2026) ---
            # Marge/liquidation calculées avec ACTUAL_LEVERAGE (1x, ce qui
            # est réellement envoyé à l'exchange aujourd'hui - cf.
            # `shared.futures_margin.ACTUAL_LEVERAGE`), jamais MAX_LEVERAGE
            # tant que les adaptateurs n'envoient pas encore ce dernier.
            notional = filled_quantity * filled_price
            margin_used = compute_required_margin(notional, ACTUAL_LEVERAGE)
            liquidation_price = compute_liquidation_price(
                entry_price=filled_price, leverage=ACTUAL_LEVERAGE, side=position_side
            )
            stop_price = compute_max_loss_stop_price(
                entry_price=filled_price,
                leverage=ACTUAL_LEVERAGE,
                side=position_side,
                max_loss_fraction_of_margin=MAX_LOSS_FRACTION_OF_MARGIN,
            )

            fill_result = await apply_fill(
                self._db_pool,
                exchange=exchange,
                symbol=symbol,
                execution_mode=self.mode_name,
                side=side,
                filled_price=filled_price,
                filled_quantity=filled_quantity,
                decision_id=decision_id,
                market_type="futures_perpetual",
                leverage=ACTUAL_LEVERAGE,
                margin_used=margin_used,
                liquidation_price_reference=liquidation_price,
            )

            if fill_result is not None and fill_result.opened:
                await self._attach_stop_loss(
                    adapter, exchange, symbol, position_side, stop_price, fill_result.position_id
                )
            elif fill_result is not None and fill_result.closed:
                await self._cancel_dangling_conditional_orders(adapter, exchange, symbol, fill_result)
        except Exception:
            status = "rejected"
            raise
        finally:
            await insert_order_row(
                self._db_pool,
                risk_check_id=risk_check_id,
                exchange=exchange,
                symbol=symbol,
                side=side,
                execution_mode=self.mode_name,
                requested_price=price,
                requested_quantity=quantity,
                filled_price=filled_price,
                filled_quantity=filled_quantity,
                slippage=slippage,
                status=status,
            )

        return OrderResult(
            order_id=exchange_order_id,
            status=status,
            filled_price=filled_price,
            filled_quantity=filled_quantity,
            slippage=slippage,
        )

    async def _attach_stop_loss(
        self,
        adapter,
        exchange: str,
        symbol: str,
        position_side: PositionSide,
        stop_price: Decimal,
        position_id: int,
    ) -> None:
        """Second appel API, jamais atomique avec l'entrée (vérifié
        contre la documentation Binance - cf. docstring de
        `data_collector/adapters/binance_futures.py`) : une position
        peut donc se retrouver brièvement, voire durablement en cas
        d'échec, SANS stop-loss. Jamais silencieux - journalisé dans
        les deux cas (absence de capacité, ou échec de l'appel)."""
        if not isinstance(adapter, SupportsConditionalOrders):
            self._publish_journal_event(
                "execution_engine.futures_position_without_stop_loss_capability",
                {"exchange": exchange, "symbol": symbol, "position_id": position_id},
            )
            return

        try:
            stop_order_id = await adapter.place_stop_loss(symbol, position_side, stop_price)
        except Exception as exc:
            self._publish_journal_event(
                "execution_engine.futures_stop_loss_placement_failed",
                {"exchange": exchange, "symbol": symbol, "position_id": position_id, "error": str(exc)},
            )
            return

        await record_conditional_order_ids(self._db_pool, position_id, stop_loss_order_id=stop_order_id)
        self._publish_journal_event(
            "execution_engine.futures_stop_loss_attached",
            {
                "exchange": exchange,
                "symbol": symbol,
                "position_id": position_id,
                "stop_price": str(stop_price),
                "order_id": stop_order_id,
            },
        )

    async def _cancel_dangling_conditional_orders(
        self, adapter, exchange: str, symbol: str, fill_result
    ) -> None:
        """Position fermée (par l'agent ou par le stop lui-même) - tout
        ordre conditionnel restant doit être annulé, jamais laissé
        traîner sur l'exchange (mandat : "annulant au passage le Stop
        et le TP restants"). Best-effort et non bloquant : un échec
        d'annulation n'empêche jamais de considérer la position comme
        fermée côté Vikeur (elle l'est réellement), mais doit être
        signalé pour vérification humaine."""
        if not isinstance(adapter, SupportsConditionalOrders):
            return

        for order_id in (fill_result.previous_stop_loss_order_id, fill_result.previous_take_profit_order_id):
            if order_id is None:
                continue
            try:
                await adapter.cancel_order(symbol, order_id)
            except Exception as exc:
                self._publish_journal_event(
                    "execution_engine.futures_conditional_order_cancel_failed",
                    {
                        "exchange": exchange,
                        "symbol": symbol,
                        "position_id": fill_result.position_id,
                        "order_id": order_id,
                        "error": str(exc),
                    },
                )

    async def _poll_fill_confirmation(
        self, adapter: ExchangeAdapter, order_id: str
    ) -> tuple[str, Decimal | None]:
        """Interroge get_order_status (Phase 20, §3) avec quelques tentatives
        avant d'abandonner - ne bloque jamais indéfiniment."""
        for _ in range(FILL_POLL_ATTEMPTS):
            status = await adapter.get_order_status(order_id)
            if status["state"] == "filled":
                return "filled", Decimal(str(status["filled_amount"]))
            if status["state"] in ("canceled", "partial-canceled"):
                return "cancelled", None
            await asyncio.sleep(FILL_POLL_INTERVAL_SECONDS)

        return "pending", None  # toujours en attente après le nombre de tentatives configuré
