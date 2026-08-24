"""Client Telegram minimal (mandat §18, Étape 10 du plan validé le
16/08/2026) - une seule responsabilité, envoyer un message à un chat_id
donné, jamais de logique de routage/formatage ici (cf. `channels.py`).

Référence : https://core.telegram.org/bots/api#sendmessage
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE_URL = "https://api.telegram.org"


class TelegramClient:
    def __init__(self, bot_token: str) -> None:
        if not bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN non configuré - requis pour tout envoi (mandat §18).")
        self._bot_token = bot_token
        self._http_client = httpx.AsyncClient(
            base_url=f"{TELEGRAM_API_BASE_URL}/bot{bot_token}", timeout=10.0
        )

    async def close(self) -> None:
        await self._http_client.aclose()

    async def send_message(self, chat_id: str, text: str, disable_notification: bool = False) -> None:
        """`disable_notification` : l'inverse de `critical` côté
        `channels.RoutedNotification` - Telegram envoie le message sans
        son/vibration quand True (mandat : sons réservés au canal
        Alerts, silencieux ailleurs)."""
        response = await self._http_client.post(
            "/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_notification": disable_notification},
        )
        if response.status_code >= 400:
            # Ne jamais lever ici : un échec d'envoi Telegram ne doit
            # jamais faire tomber le service de notifications (mandat :
            # "cela ne doit absolument pas ralentir ou bloquer la boucle
            # de trading principale" - même principe étendu au service
            # de notifications lui-même, qui doit rester résilient à
            # une panne de l'API Telegram).
            logger.error("Échec d'envoi Telegram (%s) : %s", response.status_code, response.text)
