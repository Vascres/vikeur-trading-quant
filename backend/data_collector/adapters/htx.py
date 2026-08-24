"""Adaptateur HTX (ex-Huobi) - marché Spot (Phase 7).

Respecte strictement la frontière définie en Phase 2 : ce module ne fait
aucune normalisation de symbole ni de format - il transmet les messages
HTX quasiment bruts (juste décompressés/désérialisés) au Normalizer
via Redis Pub/Sub (Phase 7, §5).

Référence API : https://huobiapi.github.io/docs/spot/v1/en/
- WebSocket marché public : wss://api.huobi.pro/ws (messages gzip)
- REST public : https://api.huobi.pro
"""

from __future__ import annotations

import asyncio
import base64
import gzip
import hashlib
import hmac
import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import quote

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

HTX_WS_URL = "wss://api.huobi.pro/ws"
HTX_REST_BASE_URL = "https://api.huobi.pro"

# Reconnexion : backoff exponentiel, plafonné (Phase 7, §4 - HTX ferme
# régulièrement les connexions, une reconnexion agressive mais bornée
# est nécessaire pour ne jamais rester silencieusement déconnecté).
INITIAL_BACKOFF_SECONDS = 1
MAX_BACKOFF_SECONDS = 30
PING_TIMEOUT_SECONDS = 10


class HTXAdapter(ExchangeAdapter):
    exchange_name = "htx"

    def __init__(
        self,
        journal_publisher=None,
        api_key: str | None = None,
        api_secret: str | None = None,
    ) -> None:
        """journal_publisher : callable(event_type: str, payload: dict) -> None
        Publie vers Redis (canal du Journal, Phase 4 §5.5) - injecté plutôt
        qu'importé directement, pour ne pas créer de dépendance interdite
        entre data_collector et le module journal (Phase 2, contrat import-linter).

        api_key/api_secret : requis uniquement pour les appels privés
        (place_order, cancel_order, get_balances - activés en Phase 12).
        Jamais requis pour la collecte de données publiques (Phase 7).
        """
        self._journal_publisher = journal_publisher
        self._api_key = api_key
        self._api_secret = api_secret
        self._account_id: str | None = None
        self._http_client = httpx.AsyncClient(base_url=HTX_REST_BASE_URL, timeout=10.0)

    def _emit_journal_event(self, event_type: str, payload: dict) -> None:
        if self._journal_publisher is not None:
            self._journal_publisher(event_type, payload)
        else:
            logger.info("event=%s payload=%s", event_type, payload)

    # ------------------------------------------------------------------
    # WebSocket - trades
    # ------------------------------------------------------------------

    async def stream_trades(self, symbols: list[str]) -> AsyncIterator[RawTradeMessage]:
        channels = [f"market.{symbol.lower()}.trade.detail" for symbol in symbols]
        async for raw_payload in self._stream_channels(channels):
            symbol = self._extract_symbol_from_channel(raw_payload.get("ch", ""))
            if symbol is None:
                continue
            yield RawTradeMessage(exchange=self.exchange_name, native_symbol=symbol, payload=raw_payload)

    # ------------------------------------------------------------------
    # WebSocket - order book (depth, agrégation step0 = la plus fine)
    # ------------------------------------------------------------------

    async def stream_order_book(self, symbols: list[str]) -> AsyncIterator[RawOrderBookMessage]:
        channels = [f"market.{symbol.lower()}.depth.step0" for symbol in symbols]
        async for raw_payload in self._stream_channels(channels):
            symbol = self._extract_symbol_from_channel(raw_payload.get("ch", ""))
            if symbol is None:
                continue
            yield RawOrderBookMessage(exchange=self.exchange_name, native_symbol=symbol, payload=raw_payload)

    # ------------------------------------------------------------------
    # Cœur commun : connexion WS, gzip, ping/pong, reconnexion avec backoff
    # ------------------------------------------------------------------

    async def _stream_channels(self, channels: list[str]) -> AsyncIterator[dict]:
        backoff = INITIAL_BACKOFF_SECONDS
        while True:
            try:
                async with websockets.connect(HTX_WS_URL, ping_interval=None) as ws:
                    for i, channel in enumerate(channels):
                        await ws.send(json.dumps({"sub": channel, "id": f"sub-{i}"}))

                    self._emit_journal_event(
                        "collector.connected",
                        {"exchange": self.exchange_name, "channels": channels},
                    )
                    backoff = INITIAL_BACKOFF_SECONDS  # reset après une connexion réussie

                    while True:
                        # Bug découvert le 14/08/2026 (ADR non requis, correctif
                        # ponctuel) : `ping_interval=None` désactive la
                        # surveillance de connexion intégrée à `websockets` -
                        # sans délai explicite ici, une connexion à moitié
                        # morte (aucune trame de fermeture jamais reçue) reste
                        # indéfiniment silencieuse, `async for` attendant un
                        # message qui ne vient plus jamais. `PING_TIMEOUT_SECONDS`
                        # existait déjà dans ce fichier, jamais branché - c'est
                        # exactement ce qui a causé 3 jours de collecte figée,
                        # sans erreur, sans reconnexion, sans que rien ne
                        # l'indique nulle part.
                        try:
                            raw_message = await asyncio.wait_for(ws.recv(), timeout=PING_TIMEOUT_SECONDS)
                        except TimeoutError:
                            self._emit_journal_event(
                                "collector.stale_connection",
                                {
                                    "exchange": self.exchange_name,
                                    "channels": channels,
                                    "silence_seconds": PING_TIMEOUT_SECONDS,
                                },
                            )
                            logger.warning(
                                "HTX WS : aucun message reçu depuis %ss - connexion probablement "
                                "morte silencieusement, reconnexion forcée.",
                                PING_TIMEOUT_SECONDS,
                            )
                            break  # sort de la boucle interne -> ferme `ws` -> reconnexion (backoff)

                        message = self._decode_message(raw_message)
                        if message is None:
                            continue

                        # Protocole HTX : répondre au ping pour éviter la déconnexion
                        # côté serveur (Phase 7, §4).
                        if "ping" in message:
                            await ws.send(json.dumps({"pong": message["ping"]}))
                            continue

                        if "subbed" in message or "status" in message and "ch" not in message:
                            continue  # accusé de réception d'abonnement, pas une donnée

                        yield message

            except (websockets.exceptions.ConnectionClosed, OSError) as exc:
                self._emit_journal_event(
                    "collector.disconnected",
                    {"exchange": self.exchange_name, "reason": str(exc), "next_retry_in_s": backoff},
                )
                logger.warning("HTX WS déconnecté (%s), reconnexion dans %ss", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                continue

            # Sortie propre de la boucle interne (timeout de silence, ci-dessus) -
            # même traitement qu'une vraie déconnexion : attendre puis retenter.
            self._emit_journal_event(
                "collector.disconnected",
                {
                    "exchange": self.exchange_name,
                    "reason": "stale_connection_timeout",
                    "next_retry_in_s": backoff,
                },
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

    @staticmethod
    def _decode_message(raw_message: bytes | str) -> dict | None:
        try:
            if isinstance(raw_message, bytes):
                raw_message = gzip.decompress(raw_message).decode("utf-8")
            return json.loads(raw_message)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Message HTX illisible, ignoré : %s", exc)
            return None

    @staticmethod
    def _extract_symbol_from_channel(channel: str) -> str | None:
        # Format HTX : "market.btcusdt.trade.detail" -> "btcusdt"
        parts = channel.split(".")
        return parts[1] if len(parts) > 1 else None

    # ------------------------------------------------------------------
    # REST - backfill / resynchronisation (Phase 7, §4)
    # ------------------------------------------------------------------

    async def fetch_recent_trades(self, symbol: str, limit: int) -> list[RawTradeMessage]:
        response = await self._http_client.get(
            "/market/history/trade",
            params={"symbol": symbol.lower(), "size": min(limit, 2000)},
        )
        response.raise_for_status()
        body = response.json()
        if body.get("status") != "ok":
            self._emit_journal_event(
                "collector.rest_error",
                {"exchange": self.exchange_name, "endpoint": "/market/history/trade", "body": body},
            )
            return []

        messages: list[RawTradeMessage] = []
        for group in body.get("data", []):
            for trade in group.get("data", []):
                messages.append(
                    RawTradeMessage(exchange=self.exchange_name, native_symbol=symbol.lower(), payload=trade)
                )
        return messages

    # ------------------------------------------------------------------
    # Signature HTX v2 (Phase 12, §5) - référence :
    # https://huobiapi.github.io/docs/spot/v1/en/
    #
    # ⚠️ Endpoints vérifiés via documentation à un instant T - à re-vérifier
    # contre la doc HTX à jour avant tout passage en capital réel (Phase 12, §5).
    # ------------------------------------------------------------------

    def _sign_request(self, method: str, path: str, extra_params: dict | None = None) -> dict:
        if not self._api_key or not self._api_secret:
            raise RuntimeError(
                "Clés API HTX non configurées (HTX_API_KEY/HTX_API_SECRET, ADR-0012) - "
                "requises pour les appels privés (Phase 12, §5)."
            )

        timestamp = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S")
        auth_params = {
            "AccessKeyId": self._api_key,
            "SignatureMethod": "HmacSHA256",
            "SignatureVersion": "2",
            "Timestamp": timestamp,
        }
        # Pour les GET, tous les paramètres entrent dans la signature ;
        # pour les POST, seuls les 4 paramètres d'authentification y entrent
        # (les paramètres de l'ordre vont dans le corps JSON) - Phase 12, §5.
        all_params = {**auth_params, **(extra_params or {})} if method == "GET" else auth_params

        sorted_items = sorted(all_params.items())
        encoded = "&".join(f"{quote(str(k), safe='')}={quote(str(v), safe='')}" for k, v in sorted_items)
        host = HTX_REST_BASE_URL.replace("https://", "")
        payload = f"{method}\n{host}\n{path}\n{encoded}"

        digest = hmac.new(self._api_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
        signature = base64.b64encode(digest).decode("utf-8")

        all_params["Signature"] = signature
        return all_params

    async def _get_account_id(self) -> str:
        if self._account_id is not None:
            return self._account_id

        params = self._sign_request("GET", "/v1/account/accounts")
        response = await self._http_client.get("/v1/account/accounts", params=params)
        response.raise_for_status()
        body = response.json()
        if body.get("status") != "ok" or not body.get("data"):
            raise RuntimeError(f"Impossible de récupérer le compte HTX : {body}")

        # Premier compte de type "spot" - suffisant en V1 (un seul compte de trading)
        spot_account = next((a for a in body["data"] if a.get("type") == "spot"), body["data"][0])
        self._account_id = str(spot_account["id"])
        return self._account_id

    async def place_order(
        self, symbol: str, side: OrderSide, quantity: Decimal, price: Decimal | None
    ) -> str:
        """`symbol` est le symbole canonique (ex. "BTC/USDT", cf.
        `decisions.symbol`) - converti en natif HTX ici. Correction d'un
        bug pré-existant (ADR-0012) : ce code faisait auparavant
        `symbol.lower()` directement sur le canonique, produisant un
        symbole invalide ("btc/usdt" au lieu de "btcusdt") - jamais
        exercé en pratique tant que le mode réel n'avait pas de chemin
        pour être réellement atteint (corrigé en ADR-0008)."""
        account_id = await self._get_account_id()
        params = self._sign_request("POST", "/v1/order/orders/place")

        order_type = f"{side.value}-limit" if price is not None else f"{side.value}-market"
        body = {
            "account-id": account_id,
            "symbol": canonical_to_native(self.exchange_name, symbol),
            "type": order_type,
            "amount": str(quantity),
            "source": "spot-api",
        }
        if price is not None:
            body["price"] = str(price)

        response = await self._http_client.post("/v1/order/orders/place", params=params, json=body)
        response.raise_for_status()
        result = response.json()

        if result.get("status") != "ok":
            self._emit_journal_event(
                "collector.order_rejected", {"exchange": self.exchange_name, "response": result}
            )
            raise RuntimeError(f"Ordre HTX rejeté : {result}")

        order_id = str(result["data"])
        self._emit_journal_event(
            "collector.order_placed",
            {"exchange": self.exchange_name, "order_id": order_id, "symbol": symbol, "side": side.value},
        )
        return order_id

    async def cancel_order(self, order_id: str) -> None:
        path = f"/v1/order/orders/{order_id}/submitcancel"
        params = self._sign_request("POST", path)
        response = await self._http_client.post(path, params=params)
        response.raise_for_status()
        result = response.json()

        if result.get("status") != "ok":
            self._emit_journal_event(
                "collector.cancel_rejected",
                {"exchange": self.exchange_name, "order_id": order_id, "response": result},
            )
            raise RuntimeError(f"Annulation d'ordre HTX rejetée : {result}")

        self._emit_journal_event(
            "collector.order_cancelled", {"exchange": self.exchange_name, "order_id": order_id}
        )

    async def get_balances(self) -> dict[str, Decimal]:
        account_id = await self._get_account_id()
        path = f"/v1/account/accounts/{account_id}/balance"
        params = self._sign_request("GET", path)
        response = await self._http_client.get(path, params=params)
        response.raise_for_status()
        result = response.json()

        if result.get("status") != "ok":
            raise RuntimeError(f"Impossible de récupérer les soldes HTX : {result}")

        balances: dict[str, Decimal] = {}
        for entry in result["data"].get("list", []):
            if entry.get("type") != "trade":
                continue
            currency = entry["currency"].upper()
            balances[currency] = balances.get(currency, Decimal(0)) + Decimal(entry["balance"])
        return balances

    async def get_order_status(self, order_id: str) -> dict:
        """Interroge le statut réel d'un ordre (Phase 20, §3 - corrige le
        manque signalé en Phase 12, §6 / Phase 15, §8)."""
        path = f"/v1/order/orders/{order_id}"
        params = self._sign_request("GET", path)
        response = await self._http_client.get(path, params=params)
        response.raise_for_status()
        result = response.json()

        if result.get("status") != "ok":
            raise RuntimeError(f"Impossible de récupérer le statut de l'ordre HTX {order_id} : {result}")

        data = result["data"]
        return {
            "state": data["state"],  # 'submitted' | 'filled' | 'partial-filled' | 'canceled' | ...
            "filled_amount": data.get("field-amount"),
            "filled_cash_amount": data.get("field-cash-amount"),
        }

    async def get_fee_rate(self, native_symbols: list[str]) -> list[dict]:
        """Frais réels du compte (ADR-0016, CostModel) - jamais une valeur
        supposée : interroge directement le palier tarifaire effectif du
        compte (prend en compte les remises VIP/jeton natif éventuelles).

        Référence API : https://huobiapi.github.io/docs/spot/v1/en/#get-current-fee-rate-applied-to-the-user
        (`GET /v2/reference/transact-fee-rate`, authentifié, paramètre
        `symbols` en minuscules séparés par des virgules).

        Retourne une liste de dicts bruts HTX (un par symbole demandé) -
        laisse `cost_model/htx_fee_fetcher.py` responsable de l'interprétation
        (choix entre taux de base et taux réel post-remise), pour garder
        cet adaptateur strictement au niveau transport (Phase 2, contrat
        de frontière déjà en place pour ce module).
        """
        path = "/v2/reference/transact-fee-rate"
        params = self._sign_request("GET", path, {"symbols": ",".join(native_symbols)})
        response = await self._http_client.get(path, params=params)
        response.raise_for_status()
        result = response.json()

        if result.get("code") != 200 or result.get("data") is None:
            raise RuntimeError(f"Impossible de récupérer les frais réels HTX : {result}")

        return result["data"]

    async def close(self) -> None:
        await self._http_client.aclose()
