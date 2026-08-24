"""Adaptateur Binance - contrats perpétuels USDⓈ-M (Étapes 7-8 du plan
validé le 16/08/2026, étend ADR-0018 à un second exchange futures).

Base URL distincte du spot (`data_collector/adapters/binance.py`,
`api.binance.com`) - les perpétuels USDⓈ-M vivent sur `fapi.binance.com`,
une API séparée mais avec le MÊME schéma d'authentification que le spot
(HMAC-SHA256 sur la query string, en-tête `X-MBX-APIKEY`) - repris à
l'identique de `BinanceAdapter._sign_params`/`_auth_headers`, jamais
centralisé entre les deux modules (même choix que HTX : chaque
adaptateur reste autonome, cf. `htx_futures.py`).

Invariant ADR-0018, révisé par décision CTO le 16/08/2026 (plafond
système à 2x, `shared.futures_margin.MAX_LEVERAGE`) mais PAS ENCORE
appliqué ici : `place_order` fixe toujours le levier du compte à 1x
AVANT d'envoyer l'ordre (`set_leverage`), jamais un paramètre de levier
passé à l'ordre lui-même - même invariant que `HTXFuturesAdapter`
(`lever_rate: 1`), vérifié en amont une seconde fois par
`FuturesNotionalExposureCapRule` (défense en profondeur, désormais
consciente du levier système plutôt qu'une simple interdiction). Faire
passer cet adaptateur à `MAX_LEVERAGE` exige que le filet de sécurité
correspondant (stop-loss automatique avant liquidation, "triptyque
d'ordres" du mandat §9) existe d'abord dans `execution_engine` - pas
construit par ce chantier, séquencement délibéré, pas un oubli.

One-Way Mode et marge Isolée sont configurés explicitement au niveau du
compte (`set_one_way_position_mode`, `set_isolated_margin`) plutôt que
supposés - Binance ne les impose pas par défaut (mandat §7 : "Vikeur
forcera chaque trade en marge Isolée").

⚠️ AVERTISSEMENT AVANT TOUTE ACTIVATION RÉELLE (même limitation assumée
que `htx_futures.py`, ADR-0018 §6, mode paper d'abord) : les chemins
d'endpoints ci-dessous sont basés sur la documentation Binance Futures
consultée au moment de l'écriture - à revérifier explicitement avant
toute clé API réelle branchée sur ce module.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import urlencode

import httpx
import websockets

from shared.futures_adapter import FuturesExchangeAdapter, FuturesPosition, PositionSide
from shared.symbol_mapping import canonical_to_native, to_canonical

logger = logging.getLogger(__name__)

BINANCE_FUTURES_REST_BASE_URL = "https://fapi.binance.com"

# Vérifié le 17/08/2026 contre la documentation Binance Open Platform en
# vigueur (Important WebSocket Change Notice) : Binance a migré son
# architecture WebSocket futures vers trois points d'entrée dédiés
# (Public/Market/Private) le 06/03/2026, avec décommissionnement
# DÉFINITIF des anciennes URLs (`wss://fstream.binance.com/ws`,
# `.../stream`) le 23/04/2026 - déjà passé à la date d'écriture.
# `forceOrder` (liquidations) appartient explicitement à la catégorie
# "Market", jamais "Public" - une connexion sans le préfixe `/market` ne
# recevrait plus aucune donnée de ce flux. De nombreux tutoriels/dépôts
# publics encore trouvables aujourd'hui utilisent encore l'ancienne URL -
# une source d'erreur silencieuse si copiée sans revérifier contre la
# doc à jour, exactement le type de piège que ce commentaire vise à
# éviter pour tout futur lecteur de ce fichier.
BINANCE_FUTURES_MARKET_WS_BASE_URL = "wss://fstream.binance.com/market"

INITIAL_BACKOFF_SECONDS = 1
MAX_BACKOFF_SECONDS = 30


@dataclass(frozen=True)
class LiquidationEvent:
    """Un ordre de liquidation forcée (mandat, agent Liquidation Cascade -
    chantier de données du 16/08/2026)."""

    exchange: str
    symbol: str  # canonique, ex. "BTC/USDT"
    side: str  # 'buy' ou 'sell' - sens de L'ORDRE DE LIQUIDATION (une liquidation de LONG se solde par un ordre SELL)
    price: Decimal
    quantity: Decimal
    notional: Decimal
    order_status: str
    event_time: datetime


def parse_liquidation_message(raw_message: str) -> LiquidationEvent | None:
    """Fonction pure, testée en isolation contre l'exemple exact de la
    documentation Binance (`Liquidation Order Streams`) - un message
    malformé ne doit jamais faire tomber le flux, seulement être ignoré
    et journalisé.

    Gère les deux formes possibles selon le mode de connexion (mandat -
    vérifié le 17/08/2026) : enveloppé `{"stream": "...", "data": {...}}`
    en mode `stream` (flux combinés, celui utilisé par
    `stream_liquidations` ci-dessous), ou nu en mode `ws` simple flux -
    `payload.get("data", payload)` couvre les deux sans dupliquer le code.

    Limitation de la donnée elle-même (documentée par Binance, pas une
    approximation de cette implémentation) : ce flux ne pousse que la
    PLUS GROSSE liquidation par symbole toutes les 1000ms - un
    échantillon, jamais un décompte exhaustif. Pendant une cascade réelle
    (nombreuses liquidations simultanées), le volume total liquidé est
    sous-compté. À prendre en compte explicitement lors de la
    calibration du signal de détection (chantier suivant), jamais
    traité comme si chaque liquidation individuelle était capturée."""
    try:
        parsed = json.loads(raw_message)
        payload = parsed.get("data", parsed)
        order = payload["o"]
        native_symbol = order["s"]
        price = Decimal(str(order["p"]))
        quantity = Decimal(str(order["q"]))
        return LiquidationEvent(
            exchange="binance",
            symbol=to_canonical("binance", native_symbol.lower()),
            side="buy" if order["S"] == "BUY" else "sell",
            price=price,
            quantity=quantity,
            notional=price * quantity,
            order_status=order["X"],
            event_time=datetime.fromtimestamp(order["T"] / 1000, tz=UTC),
        )
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        logger.warning("Message de liquidation Binance illisible, ignoré : %r", raw_message)
        return None


# Codes d'erreur Binance signifiant "déjà dans l'état demandé" - jamais
# un échec réel, ne doivent jamais faire lever d'exception (vérifié
# contre la documentation Binance Open Platform au moment de l'écriture).
NO_NEED_TO_CHANGE_MARGIN_TYPE = -4046
NO_NEED_TO_CHANGE_POSITION_SIDE = -4059


class BinanceFuturesAdapter(FuturesExchangeAdapter):
    exchange_name = "binance"

    def __init__(
        self, api_key: str | None = None, api_secret: str | None = None, journal_publisher=None
    ) -> None:
        super().__init__(api_key=api_key, api_secret=api_secret)
        self._http_client = httpx.AsyncClient(base_url=BINANCE_FUTURES_REST_BASE_URL, timeout=10.0)
        # `journal_publisher` : callable(event_type: str, payload: dict) -> None,
        # même contrat que `shared.exchange_adapter.ExchangeAdapter`
        # (streaming spot) - dupliqué ici plutôt qu'hérité, cette classe
        # reste volontairement parallèle à `ExchangeAdapter`, pas une
        # extension de celui-ci (cf. docstring de `shared/futures_adapter.py`).
        self._journal_publisher = journal_publisher

    def _emit_journal_event(self, event_type: str, payload: dict) -> None:
        if self._journal_publisher is not None:
            self._journal_publisher(event_type, payload)

    async def close(self) -> None:
        await self._http_client.aclose()

    def _sign_params(self, params: dict) -> dict:
        """Identique à `BinanceAdapter._sign_params` (spot) - même schéma
        d'authentification Binance, seul l'hôte change."""
        if not self._api_key or not self._api_secret:
            raise RuntimeError(
                "Clés API Binance Futures non configurées (BINANCE_FUTURES_API_KEY/"
                "BINANCE_FUTURES_API_SECRET, ADR-0018) - requises pour tout appel privé."
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

    def _native_symbol(self, symbol: str) -> str:
        return canonical_to_native(self.exchange_name, symbol).upper()

    async def _is_already_configured_error(self, response: httpx.Response, expected_code: int) -> bool:
        if response.status_code < 400:
            return False
        try:
            return response.json().get("code") == expected_code
        except ValueError:
            return False

    # ------------------------------------------------------------------
    # Configuration du compte (mandat §7) - à appeler avant le premier
    # ordre sur un symbole, jamais supposée déjà faite.
    # ------------------------------------------------------------------

    async def set_one_way_position_mode(self) -> None:
        """Force le mode One-Way (jamais Hedge Mode) - mandat §7 : "Pas
        de Hedge Mode... inutile pour nos stratégies directionnelles et
        cela complique le Risk Engine." Un compte déjà en One-Way
        renvoie -4059, jamais traité comme une erreur."""
        params = self._sign_params({"dualSidePosition": "false"})
        response = await self._http_client.post(
            "/fapi/v1/positionSide/dual", params=params, headers=self._auth_headers()
        )
        if await self._is_already_configured_error(response, NO_NEED_TO_CHANGE_POSITION_SIDE):
            return
        response.raise_for_status()

    async def set_isolated_margin(self, symbol: str) -> None:
        """Force la marge Isolée pour ce symbole - mandat §7 : "Si un
        trade déraille... Binance va siphonner l'intégralité du compte
        [en Cross Margin]. En Isolated Margin... le risque absolu est
        limité à [la marge de ce trade]." Un symbole déjà isolé renvoie
        -4046, jamais traité comme une erreur. Binance refuse ce
        changement s'il existe déjà une position ou un ordre ouvert sur
        ce symbole - à appeler avant toute position, jamais après."""
        native = self._native_symbol(symbol)
        params = self._sign_params({"symbol": native, "marginType": "ISOLATED"})
        response = await self._http_client.post(
            "/fapi/v1/marginType", params=params, headers=self._auth_headers()
        )
        if await self._is_already_configured_error(response, NO_NEED_TO_CHANGE_MARGIN_TYPE):
            return
        response.raise_for_status()

    async def set_leverage(self, symbol: str, leverage: int = 1) -> None:
        """Fixe le levier du COMPTE pour ce symbole - jamais un paramètre
        de l'ordre lui-même. Appelé avec `leverage=1` par `place_order`
        (invariant ADR-0018, cf. docstring du module) ; exposé avec un
        paramètre explicite pour rester prêt le jour où une décision
        architecturale consciente autoriserait un levier réel."""
        native = self._native_symbol(symbol)
        params = self._sign_params({"symbol": native, "leverage": leverage})
        response = await self._http_client.post(
            "/fapi/v1/leverage", params=params, headers=self._auth_headers()
        )
        response.raise_for_status()

    # ------------------------------------------------------------------
    # Contrat FuturesExchangeAdapter (ADR-0018)
    # ------------------------------------------------------------------

    async def get_positions(self, symbol: str) -> list[FuturesPosition]:
        native = self._native_symbol(symbol)
        params = self._sign_params({"symbol": native})
        response = await self._http_client.get(
            "/fapi/v2/positionRisk", params=params, headers=self._auth_headers()
        )
        response.raise_for_status()
        entries = response.json()

        positions = []
        for entry in entries:
            amount = Decimal(str(entry["positionAmt"]))
            if amount == 0:
                continue  # Binance renvoie toujours une ligne par symbole, même à plat (positionAmt=0)
            positions.append(
                FuturesPosition(
                    symbol=symbol,
                    side=PositionSide.LONG if amount > 0 else PositionSide.SHORT,
                    quantity=abs(amount),
                    entry_price=Decimal(str(entry["entryPrice"])),
                    mark_price=Decimal(str(entry["markPrice"])),
                    unrealized_pnl=Decimal(str(entry["unRealizedProfit"])),
                )
            )
        return positions

    async def place_order(self, symbol: str, side: PositionSide, quantity: Decimal) -> str:
        await self.set_leverage(symbol, leverage=1)  # ADR-0018 : jamais autre chose que 1

        native = self._native_symbol(symbol)
        params = self._sign_params(
            {
                "symbol": native,
                "side": "BUY" if side == PositionSide.LONG else "SELL",
                "type": "MARKET",
                "quantity": str(quantity),
            }
        )
        response = await self._http_client.post("/fapi/v1/order", params=params, headers=self._auth_headers())
        response.raise_for_status()
        result = response.json()
        return str(result["orderId"])

    async def close_position(self, symbol: str, side: PositionSide, quantity: Decimal) -> str:
        """`reduceOnly=true` (mandat §9 : "un ordre STOP_MARKET... qui ne
        peut que fermer une position, jamais en ouvrir une nouvelle par
        erreur") - même filet de sécurité pour toute clôture, pas
        seulement pour un stop-loss dédié."""
        native = self._native_symbol(symbol)
        params = self._sign_params(
            {
                "symbol": native,
                # Clôturer une position LONG = vendre ; clôturer une position SHORT = racheter.
                "side": "SELL" if side == PositionSide.LONG else "BUY",
                "type": "MARKET",
                "quantity": str(quantity),
                "reduceOnly": "true",
            }
        )
        response = await self._http_client.post("/fapi/v1/order", params=params, headers=self._auth_headers())
        response.raise_for_status()
        result = response.json()
        return str(result["orderId"])

    async def get_funding_rate(self, symbol: str) -> Decimal:
        """Taux de financement réel - endpoint public, aucune
        authentification requise (même principe que HTX : donnée de
        marché publique, pas propre au compte).

        Référence : `GET /fapi/v1/premiumIndex` (`lastFundingRate`) -
        renvoie une fraction par période de financement (8h), jamais
        convertie en bps ici (responsabilité de l'appelant, même
        contrat que `HTXFuturesAdapter.get_funding_rate`)."""
        native = self._native_symbol(symbol)
        response = await self._http_client.get("/fapi/v1/premiumIndex", params={"symbol": native})
        response.raise_for_status()
        result = response.json()
        return Decimal(str(result["lastFundingRate"]))

    # ------------------------------------------------------------------
    # Solde de marge (17/08/2026) - implémente le Protocol
    # `shared.futures_adapter.SupportsAccountBalance`. Trou fonctionnel
    # découvert le 17/08/2026 : `portfolio/main.py` n'a jamais snapshotté
    # aucun solde futures, faute de cette méthode - la Live Vault du
    # frontend n'a donc jamais pu afficher le compte Binance Futures.
    # ------------------------------------------------------------------

    async def get_account_balance(self) -> dict[str, Decimal]:
        """Vérifié le 17/08/2026 contre la documentation Binance Open
        Platform (`Futures Account Balance V3`, USER_DATA) : `GET
        /fapi/v3/balance` renvoie une liste d'actifs, chacun avec
        `balance` (solde total du portefeuille) et `availableBalance`
        (disponible, hors marge déjà engagée). Utilise `balance` -
        même sémantique que `ExchangeAdapter.get_balances()` côté spot
        (solde total détenu, pas seulement le disponible), pour rester
        directement comparable dans la Live Vault."""
        params = self._sign_params({})
        response = await self._http_client.get(
            "/fapi/v3/balance", params=params, headers=self._auth_headers()
        )
        response.raise_for_status()
        entries = response.json()
        return {entry["asset"]: Decimal(str(entry["balance"])) for entry in entries}

    # ------------------------------------------------------------------
    # Flux de liquidations (agent Liquidation Cascade - chantier de
    # données du 16/08/2026) - même schéma de reconnexion avec backoff
    # exponentiel que `BinanceAdapter._stream_channels` (spot), reproduit
    # ici plutôt que partagé : cette classe reste volontairement
    # parallèle à `ExchangeAdapter`, jamais une extension de celui-ci.
    # ------------------------------------------------------------------

    async def stream_liquidations(self, symbols_native: list[str]) -> AsyncIterator[str]:
        """`symbols_native` : symboles au format Binance en minuscules
        (ex. "btcusdt") - cohérent avec la convention déjà utilisée par
        `BinanceAdapter.stream_trades` (spot). Retourne le message brut
        (str) - le parsing est délibérément séparé
        (`parse_liquidation_message`), pour rester testable sans mock
        réseau."""
        streams = "/".join(f"{s}@forceOrder" for s in symbols_native)
        url = f"{BINANCE_FUTURES_MARKET_WS_BASE_URL}/stream?streams={streams}"
        backoff = INITIAL_BACKOFF_SECONDS

        while True:
            try:
                async with websockets.connect(url) as ws:
                    self._emit_journal_event(
                        "collector.ws_connected", {"exchange": self.exchange_name, "stream": "liquidations"}
                    )
                    backoff = INITIAL_BACKOFF_SECONDS  # reconnexion réussie - on relâche le backoff

                    async for raw_message in ws:
                        yield raw_message

            except (websockets.ConnectionClosed, OSError) as exc:
                self._emit_journal_event(
                    "collector.ws_disconnected",
                    {"exchange": self.exchange_name, "stream": "liquidations", "error": str(exc)},
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

    # ------------------------------------------------------------------
    # Triptyque d'ordres (mandat §9, 16/08/2026) - implémente le
    # Protocol `shared.futures_adapter.SupportsConditionalOrders`.
    #
    # Vérifié via la documentation Binance Open Platform au moment de
    # l'écriture : contrairement à d'autres exchanges, Binance Futures
    # N'OFFRE PAS de rattachement atomique d'un stop-loss à l'ordre
    # d'entrée - `place_order` (marché) et `place_stop_loss` (ordre
    # conditionnel STOP_MARKET) sont TOUJOURS deux appels API distincts,
    # jamais garantis atomiques par l'exchange lui-même. C'est
    # `execution_engine/modes/real.py` qui les enchaîne et qui reste
    # responsable de la cohérence si le second appel échoue après que
    # le premier a réussi (position ouverte SANS stop-loss, journalisé
    # bruyamment, jamais silencieux).
    # ------------------------------------------------------------------

    async def place_stop_loss(self, symbol: str, position_side: PositionSide, stop_price: Decimal) -> str:
        """`closePosition=true` plutôt que `reduceOnly` + quantité
        explicite : ferme la position entière au marché dès le
        déclenchement, sans avoir à connaître/resynchroniser la
        quantité exacte au moment où le stop se déclenche (mandat §8 :
        jamais un stop partiel)."""
        native = self._native_symbol(symbol)
        params = self._sign_params(
            {
                "symbol": native,
                # Clôturer un LONG = vendre ; clôturer un SHORT = racheter (même
                # logique que close_position ci-dessus).
                "side": "SELL" if position_side == PositionSide.LONG else "BUY",
                "type": "STOP_MARKET",
                "stopPrice": str(stop_price),
                "closePosition": "true",
            }
        )
        response = await self._http_client.post("/fapi/v1/order", params=params, headers=self._auth_headers())
        response.raise_for_status()
        result = response.json()
        return str(result["orderId"])

    async def cancel_order(self, symbol: str, order_id: str) -> None:
        native = self._native_symbol(symbol)
        params = self._sign_params({"symbol": native, "orderId": order_id})
        response = await self._http_client.delete(
            "/fapi/v1/order", params=params, headers=self._auth_headers()
        )
        # Code -2011 ("Unknown order sent") = déjà annulé/exécuté/expiré -
        # jamais un échec réel pour cet appelant (l'objectif, "ne plus
        # avoir d'ordre conditionnel en attente", est déjà atteint).
        if response.status_code >= 400:
            try:
                already_gone = response.json().get("code") == -2011
            except ValueError:
                already_gone = False
            if not already_gone:
                response.raise_for_status()
