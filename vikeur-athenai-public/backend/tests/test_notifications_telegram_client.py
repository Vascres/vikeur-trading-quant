"""Tests de notifications.telegram_client (mandat §18, Étape 10, 16/08/2026)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from notifications.telegram_client import TelegramClient


def test_requires_a_bot_token():
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN non configuré"):
        TelegramClient("")


@pytest.mark.asyncio
async def test_send_message_posts_the_expected_payload():
    client = TelegramClient("fake-token")
    fake_response = MagicMock()
    fake_response.status_code = 200
    client._http_client.post = AsyncMock(return_value=fake_response)

    await client.send_message("12345", "Bonjour", disable_notification=True)

    _, kwargs = client._http_client.post.call_args
    assert kwargs["json"] == {"chat_id": "12345", "text": "Bonjour", "disable_notification": True}
    await client.close()


@pytest.mark.asyncio
async def test_send_message_never_raises_on_telegram_error():
    """Mandat : une panne Telegram ne doit jamais faire tomber le
    service de notifications lui-même."""
    client = TelegramClient("fake-token")
    fake_response = MagicMock()
    fake_response.status_code = 429
    fake_response.text = "Too Many Requests"
    client._http_client.post = AsyncMock(return_value=fake_response)

    await client.send_message("12345", "Bonjour")  # ne doit pas lever
    await client.close()
