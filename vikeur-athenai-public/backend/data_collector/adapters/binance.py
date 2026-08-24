"""Adaptateur Binance - second exchange (ADR-0012).

Structurellement calqué sur `htx.py` (Phase 7/12) : même contrat
(`ExchangeAdapter`), même niveau de rigueur, même limitation assumée sur
le prix de remplissage réel. Diffère de HTX sur deux points génuinement
propres à Binance (documentés au fil du code, pas copiés aveuglément
depuis HTX) : messages WebSocket en JSON simple (pas de gzip), et
authentification par en-tête `X-MBX-APIKEY` plutôt que des paramètres
d'authentification dans la query string.

Référence API : https://binance-docs.github.io/apidocs/spot/en/
- WebSocket marché public (flux combinés) : wss://stream.binance.com:9443/stream
- REST public/privé : https://api.binance.com

⚠️ Endpoints vérifiés via documentation à un instant T - à re-vérifier
contre la doc Binance à jour avant tout passage en capital réel (même
limitation assumée que HTX, Phase 12, §5).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections.abc import AsyncIterator
from decimal import Decimal
from urllib.parse import urlencode

import httpx
import websockets

from shared.exchange_adapter import (
    ExchangeAdapter,
    OrderSide,
    RawOrderBookMessage,
    RawTradeMessage,
)
from shared.symbol_mapping import canonical_to_native

logger = logging.getLogger(__name__)

BINANCE_WS_URL = "wss://stream.binance.com:9443/stream"
BINANCE_REST_BASE_URL = "https://api.binance.com"

INITIAL_BACKOFF_SECONDS = 1
MAX_BACKOFF_SECONDS = 30

# Binance ferme les connexions combinées après 24h - une reconnexion
# bornée est nécessaire, comme pour HTX (Phase 7, §4), même si le motif
# de coupure diffère (limite de durée plutôt que fermetures fréquentes).


class BinanceAdapter(ExchangeAdapter):
    exchange_name = "binance"

    def __init__(
        self,
        journal_publisher=None,
        api_key: str | None = None,
        api_secret: str | None = None,
    ) -> None:
        """journal_publisher : callable(event_type: str, payload: dict) -> None.
        api_key/api_secret : requis uniquement pour les appels privés
        (place_order, cancel_order, get_balances) - jamais requis pour la
        collecte de données publiques."""
        self._journal_publisher = journal_publisher
        self._api_key = api_key
        self._api_secret = api_secret
        self._http_client = httpx.AsyncClient(base_url=BINANCE_REST_BASE_URL, timeout=10.0)

    def _emit_journal_event(self, event_type: str, payload: dict) -> None:
        if self._journal_publisher is not None:
            self._journal_publisher(event_type, payload)
        else:
            logger.info("event=%s payload=%s", event_type, payload)

    # ------------------------------------------------------------------
    # Données de marché publiques
    # ------------------------------------------------------------------

    async def stream_trades(self, symbols: list[str]) -> AsyncIterator[RawTradeMessage]:
        streams = [f"{symbol.lower()}@trade" for symbol in symbols]
        async for message in self._stream_channels(streams):
            native_symbol = message["data"]["s"].lower()
            yield RawTradeMessage(
                exchange=self.exchange_name, native_symbol=native_symbol, payload=message["data"]
            )

    async def stream_order_book(self, symbols: list[str]) -> AsyncIterator[RawOrderBookMessage]:
        # depth20@1000ms (19/08/2026, corrigé depuis @100ms) : les 20
        # premiers niveaux, rafraîchis toutes les SECONDES, pas toutes
        # les 100ms. Bug réel trouvé le 19/08/2026 (disque VPS saturé
        # deux nuits de suite) : rien dans le pipeline ne consulte
        # jamais le carnet d'ordres plus vite qu'une fois par minute
        # (feature_engine, COMPUTE_INTERVAL_SECONDS=60, ne lit que le
        # DERNIER instantané à chaque cycle) - @100ms écrivait donc
        # ~600 fois plus souvent que ce qui serait jamais réellement lu,
        # ~28 lignes/seconde mesurées en production sur 3 symboles,
        # jusqu'à ~6,9 Go rien que pour ce flux en quelques jours. @1000ms
        # reste 60x plus fréquent que la lecture réelle - large marge,
        # jamais un goulot d'étranglement pour feature_engine, tout en
        # divisant ce poste par 10.
        streams = [f"{symbol.lower()}@depth20@1000ms" for symbol in symbols]
        async for message in self._stream_channels(streams):
            # Le flux depth combiné ne porte pas le symbole dans la charge
            # utile elle-même - extrait du nom du flux ("btcusdt@depth20@1000ms").
            native_symbol = message["stream"].split("@")[0]
            yield RawOrderBookMessage(
                exchange=self.exchange_name, native_symbol=native_symbol, payload=message["data"]
            )

    async def _stream_channels(self, channels: list[str]) -> AsyncIterator[dict]:
        url = f"{BINANCE_WS_URL}?streams={'/'.join(channels)}"
        backoff = INITIAL_BACKOFF_SECONDS

        while True:
            try:
                async with websockets.connect(url) as ws:
                    self._emit_journal_event("collector.ws_connected", {"exchange": self.exchange_name})
                    backoff = INITIAL_BACKOFF_SECONDS  # reconnexion réussie - on relâche le backoff

                    async for raw_message in ws:
                        decoded = self._decode_message(raw_message)
                        if decoded is not None:
                            yield decoded

            except (websockets.ConnectionClosed, OSError) as exc:
                self._emit_journal_event(
                    "collector.ws_disconnected", {"exchange": self.exchange_name, "error": str(exc)}
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

    @staticmethod
    def _decode_message(raw_message: bytes | str) -> dict | None:
        # Contrairement à HTX, les messages Binance ne sont jamais
        # compressés (gzip) sur le flux combiné public - différence
        # documentée, pas une omission.
        try:
            return json.loads(raw_message)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    async def fetch_recent_trades(self, symbol: str, limit: int) -> list[RawTradeMessage]:
        response = await self._http_client.get(
            "/api/v3/trades", params={"symbol": symbol.upper(), "limit": min(limit, 1000)}
        )
        response.raise_for_status()
        trades = response.json()

        return [
            RawTradeMessage(exchange=self.exchange_name, native_symbol=symbol.lower(), payload=trade)
            for trade in trades
        ]

    # ------------------------------------------------------------------
    # Trading (Phase 12, §5 ; ADR-0012)
    # ------------------------------------------------------------------

    def _sign_params(self, params: dict) -> dict:
        if not self._api_key or not self._api_secret:
            raise RuntimeError(
                "Clés API Binance non configurées (BINANCE_API_KEY/BINANCE_API_SECRET, ADR-0012) - "
                "requises pour les appels privés."
            )

        signed_params = {**params, "timestamp": int(time.time() * 1000)}
        query = urlencode(signed_params)
        signature = hmac.new(
            self._api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        signed_params["signature"] = signature
        return signed_params

    def _auth_headers(self) -> dict:
        return {"X-MBX-APIKEY": self._api_key or ""}

    async def place_order(
        self, symbol: str, side: OrderSide, quantity: Decimal, price: Decimal | None
    ) -> str:
        """`symbol` est le symbole canonique (ex. "BTC/USDT") - converti
        en natif Binance ici (même correction que HTX, ADR-0012)."""
        native_symbol = canonical_to_native(self.exchange_name, symbol).upper()

        params = {
            "symbol": native_symbol,
            "side": "BUY" if side == OrderSide.BUY else "SELL",
            "type": "LIMIT" if price is not None else "MARKET",
            "quantity": str(quantity),
        }
        if price is not None:
            params["price"] = str(price)
            params["timeInForce"] = "GTC"

        signed = self._sign_params(params)
        response = await self._http_client.post("/api/v3/order", params=signed, headers=self._auth_headers())

        if response.status_code >= 400:
            self._emit_journal_event(
                "collector.order_rejected", {"exchange": self.exchange_name, "response": response.text}
            )
            response.raise_for_status()

        result = response.json()
        order_id = str(result["orderId"])
        self._emit_journal_event(
            "collector.order_placed",
            {"exchange": self.exchange_name, "order_id": order_id, "symbol": symbol, "side": side.value},
        )
        return order_id

    async def cancel_order(self, order_id: str, symbol: str | None = None) -> None:
        """Binance exige le symbole en plus de l'id d'ordre pour annuler
        (contrairement à HTX) - `symbol` doit être fourni en pratique par
        l'appelant ; limitation de contrat documentée (ADR-0012) plutôt
        que silencieuse : lève explicitement si absent."""
        if symbol is None:
            raise ValueError("BinanceAdapter.cancel_order nécessite `symbol` (contrainte propre à Binance).")

        params = {"symbol": canonical_to_native(self.exchange_name, symbol).upper(), "orderId": order_id}
        signed = self._sign_params(params)
        response = await self._http_client.delete(
            "/api/v3/order", params=signed, headers=self._auth_headers()
        )

        if response.status_code >= 400:
            self._emit_journal_event(
                "collector.cancel_rejected",
                {"exchange": self.exchange_name, "order_id": order_id, "response": response.text},
            )
            response.raise_for_status()

        self._emit_journal_event(
            "collector.order_cancelled", {"exchange": self.exchange_name, "order_id": order_id}
        )

    async def get_balances(self) -> dict[str, Decimal]:
        signed = self._sign_params({})
        response = await self._http_client.get("/api/v3/account", params=signed, headers=self._auth_headers())
        response.raise_for_status()
        result = response.json()

        balances: dict[str, Decimal] = {}
        for entry in result.get("balances", []):
            free = Decimal(entry["free"])
            if free > 0:
                balances[entry["asset"].upper()] = free
        return balances

    async def get_order_status(self, order_id: str, symbol: str | None = None) -> dict:
        """Retourne la même forme que HTXAdapter.get_order_status (Phase 20,
        §3) pour rester interchangeable côté `RealExecutionMode` - traduit
        le vocabulaire d'état Binance vers le vocabulaire déjà utilisé."""
        if symbol is None:
            raise ValueError(
                "BinanceAdapter.get_order_status nécessite `symbol` (contrainte propre à Binance)."
            )

        params = {"symbol": canonical_to_native(self.exchange_name, symbol).upper(), "orderId": order_id}
        signed = self._sign_params(params)
        response = await self._http_client.get("/api/v3/order", params=signed, headers=self._auth_headers())
        response.raise_for_status()
        data = response.json()

        state_map = {
            "FILLED": "filled",
            "CANCELED": "canceled",
            "EXPIRED": "canceled",
            "REJECTED": "canceled",
            "PARTIALLY_FILLED": "partial-filled",
            "NEW": "submitted",
        }
        return {
            "state": state_map.get(data["status"], "submitted"),
            "filled_amount": data.get("executedQty"),
            "filled_cash_amount": data.get("cummulativeQuoteQty"),
        }

    async def get_fee_rate(self, native_symbols: list[str]) -> list[dict]:
        """Frais réels du compte (chantier CostModel unique, 16/08/2026 -
        étend ADR-0016 à Binance) - jamais une valeur supposée : interroge
        directement le palier tarifaire effectif du compte.

        Référence API : https://binance-docs.github.io/apidocs/spot/en/#trade-fee-user_data
        (`GET /sapi/v1/asset/tradeFee`, authentifié). Contrairement à HTX,
        Binance renvoie déjà le taux net de toute remise VIP/BNB appliquée -
        pas de distinction taux de base/taux réel à faire côté appelant
        (cf. `cost_model/binance_fee_fetcher.py`).

        `native_symbols` attendus en majuscules (ex. "BTCUSDT", format
        natif Binance) - filtre côté client la réponse complète du compte
        (l'endpoint ne permet de filtrer que sur un seul symbole à la
        fois côté serveur, un appel groupé est donc plus efficace ici
        qu'un appel par symbole)."""
        signed = self._sign_params({})
        response = await self._http_client.get(
            "/sapi/v1/asset/tradeFee", params=signed, headers=self._auth_headers()
        )
        response.raise_for_status()
        result = response.json()
        requested = set(native_symbols)
        return [entry for entry in result if entry.get("symbol") in requested]

    async def close(self) -> None:
        await self._http_client.aclose()
