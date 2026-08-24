"""Adaptateur HTX - contrats perpétuels USDT-margined (ADR-0018).

Base URL distincte de l'API spot (`data_collector/adapters/htx.py`,
`api.huobi.pro`) - les perpétuels HTX vivent sur `api.hbdm.com`, une
API entièrement séparée (Référence : https://huobiapi.github.io/docs/usdt_swap/v1/en/).

Le schéma d'authentification HMAC (paramètres AccessKeyId/SignatureMethod/
SignatureVersion/Timestamp/Signature, tri alphabétique, `HmacSHA256`) est
documenté par HTX comme partagé entre tous ses produits (spot, futures,
swaps) - repris ici à l'identique de `HTXAdapter._sign_request`, seul
l'hôte cible change.

⚠️ AVERTISSEMENT AVANT TOUTE ACTIVATION RÉELLE (ADR-0018 §6, mode paper
d'abord) : les noms d'endpoints ci-dessous (`/linear-swap-api/v1/...`)
sont basés sur la documentation HTX consultée au moment de l'écriture -
HTX a déjà fait migrer certains endpoints de requête de v1 vers v3 par
le passé (annonce HTX de septembre 2022, "swap_hisorders" v1→v3) sans
changer les autres. **Revérifier explicitement chaque chemin contre la
documentation HTX Futures en vigueur avant toute clé API réelle branchée
sur ce module** - jamais supposé stable indéfiniment.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import quote

import httpx

from shared.futures_adapter import FuturesExchangeAdapter, FuturesPosition, PositionSide
from shared.symbol_mapping import canonical_to_native

logger = logging.getLogger(__name__)

HTX_FUTURES_REST_BASE_URL = "https://api.hbdm.com"


class HTXFuturesAdapter(FuturesExchangeAdapter):
    exchange_name = "htx"

    def __init__(self, api_key: str | None = None, api_secret: str | None = None) -> None:
        super().__init__(api_key=api_key, api_secret=api_secret)
        self._http_client = httpx.AsyncClient(base_url=HTX_FUTURES_REST_BASE_URL, timeout=10.0)

    async def close(self) -> None:
        await self._http_client.aclose()

    def _sign_request(self, method: str, path: str, extra_params: dict | None = None) -> dict:
        """Identique à `HTXAdapter._sign_request` (spot) - même schéma
        d'authentification Huobi/HTX, seul l'hôte change (ADR-0018)."""
        if not self._api_key or not self._api_secret:
            raise RuntimeError(
                "Clés API HTX Futures non configurées (HTX_FUTURES_API_KEY/HTX_FUTURES_API_SECRET, "
                "ADR-0018) - requises pour tout appel privé."
            )

        timestamp = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S")
        auth_params = {
            "AccessKeyId": self._api_key,
            "SignatureMethod": "HmacSHA256",
            "SignatureVersion": "2",
            "Timestamp": timestamp,
        }
        all_params = {**auth_params, **(extra_params or {})} if method == "GET" else auth_params

        sorted_items = sorted(all_params.items())
        encoded = "&".join(f"{quote(str(k), safe='')}={quote(str(v), safe='')}" for k, v in sorted_items)
        host = HTX_FUTURES_REST_BASE_URL.replace("https://", "")
        payload = f"{method}\n{host}\n{path}\n{encoded}"

        digest = hmac.new(self._api_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
        signature = base64.b64encode(digest).decode("utf-8")

        all_params["Signature"] = signature
        return all_params

    def _contract_code(self, symbol: str) -> str:
        """HTX Futures identifie les contrats perpétuels par un code
        dédié (ex. "BTC-USDT"), distinct du symbole spot natif
        ("btcusdt") - à confirmer précisément contre la documentation
        avant activation réelle (cf. avertissement du module)."""
        native = canonical_to_native(self.exchange_name, symbol)  # ex. "btcusdt"
        base = native.replace("usdt", "").upper()
        return f"{base}-USDT"

    async def get_positions(self, symbol: str) -> list[FuturesPosition]:
        path = "/linear-swap-api/v1/swap_position_info"
        params = self._sign_request("POST", path)
        body = {"contract_code": self._contract_code(symbol)}

        response = await self._http_client.post(path, params=params, json=body)
        response.raise_for_status()
        result = response.json()

        if result.get("status") != "ok":
            raise RuntimeError(f"Impossible de récupérer les positions futures HTX : {result}")

        positions = []
        for entry in result.get("data", []):
            positions.append(
                FuturesPosition(
                    symbol=symbol,
                    side=PositionSide.LONG if entry["direction"] == "buy" else PositionSide.SHORT,
                    quantity=Decimal(str(entry["volume"])),
                    entry_price=Decimal(str(entry["cost_open"])),
                    mark_price=Decimal(str(entry.get("mark_price", entry["cost_open"]))),
                    unrealized_pnl=Decimal(str(entry.get("profit_unreal", 0))),
                )
            )
        return positions

    async def place_order(self, symbol: str, side: PositionSide, quantity: Decimal) -> str:
        path = "/linear-swap-api/v1/swap_order"
        params = self._sign_request("POST", path)
        body = {
            "contract_code": self._contract_code(symbol),
            "direction": "buy" if side == PositionSide.LONG else "sell",
            "offset": "open",
            "lever_rate": 1,  # ADR-0018 : jamais autre chose que 1 - invariant également vérifié
            #                   en amont par FuturesNotionalExposureCapRule (défense en profondeur).
            "volume": str(quantity),
            "order_price_type": "market",
        }

        response = await self._http_client.post(path, params=params, json=body)
        response.raise_for_status()
        result = response.json()

        if result.get("status") != "ok":
            raise RuntimeError(f"Ordre futures HTX rejeté : {result}")

        return str(result["data"]["order_id"])

    async def close_position(self, symbol: str, side: PositionSide, quantity: Decimal) -> str:
        path = "/linear-swap-api/v1/swap_order"
        params = self._sign_request("POST", path)
        body = {
            "contract_code": self._contract_code(symbol),
            # Clôturer une position LONG = vendre ; clôturer une position SHORT = racheter.
            "direction": "sell" if side == PositionSide.LONG else "buy",
            "offset": "close",
            "lever_rate": 1,
            "volume": str(quantity),
            "order_price_type": "market",
        }

        response = await self._http_client.post(path, params=params, json=body)
        response.raise_for_status()
        result = response.json()

        if result.get("status") != "ok":
            raise RuntimeError(f"Clôture de position futures HTX rejetée : {result}")

        return str(result["data"]["order_id"])

    async def get_funding_rate(self, symbol: str) -> Decimal:
        """Taux de financement réel (ADR-0020, complète le stub laissé
        explicitement non implémenté par ADR-0018 §3.4).

        Endpoint public, aucune authentification requise (contrairement
        au reste de cet adaptateur) - HTX documente ce point explicitement
        ("Subscribe to funding rate push with no authentication required"),
        cohérent avec le fait que le funding est une donnée de marché
        publique, pas une information propre au compte.

        Référence : https://www.htx.com/support/44958157384677
        (`GET /linear-swap-api/v1/swap_funding_rate`, paramètre
        `contract_code`).
        """
        path = "/linear-swap-api/v1/swap_funding_rate"
        response = await self._http_client.get(path, params={"contract_code": self._contract_code(symbol)})
        response.raise_for_status()
        result = response.json()

        if result.get("status") != "ok" or result.get("data") is None:
            raise RuntimeError(f"Impossible de récupérer le funding HTX pour {symbol} : {result}")

        # HTX renvoie une fraction par période de financement (8h) - ex.
        # "0.000100" pour 0,01 % - jamais convertie en bps ici : cette
        # conversion est la responsabilité de l'appelant (cf.
        # cost_model/htx_funding_fetcher.py), pour que cet adaptateur
        # reste au niveau transport, comme le reste de son contrat
        # (même principe que get_fee_rate sur l'adaptateur spot,
        # ADR-0016).
        return Decimal(str(result["data"]["funding_rate"]))
