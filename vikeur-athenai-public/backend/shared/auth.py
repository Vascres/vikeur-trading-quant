"""Authentification et rate limiting de l'API (Module 1 - Sécurisation).

Dépendance FastAPI appliquée à toutes les routes sauf /health.
"""

import os
import secrets
import time

import redis.asyncio as redis
from fastapi import Header, HTTPException, Request

API_AUTH_TOKEN = os.environ.get("API_AUTH_TOKEN", "")
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "30"))
RATE_LIMIT_WINDOW_SECONDS = 60


def verify_token(authorization: str = Header(default="")) -> None:
    """Vérifie le jeton Bearer en temps constant (Module 1, §5)."""
    if not API_AUTH_TOKEN:
        raise HTTPException(status_code=500, detail="API_AUTH_TOKEN non configuré côté serveur.")

    expected = f"Bearer {API_AUTH_TOKEN}"
    if not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Authentification requise ou invalide.")


async def enforce_rate_limit(request: Request, redis_client: redis.Redis) -> None:
    """Limite le débit par IP via un compteur Redis avec expiration (Module 1, §4.3)."""
    client_ip = request.client.host if request.client else "unknown"
    key = f"ratelimit:{client_ip}:{int(time.time()) // RATE_LIMIT_WINDOW_SECONDS}"

    current = await redis_client.incr(key)
    if current == 1:
        await redis_client.expire(key, RATE_LIMIT_WINDOW_SECONDS)

    if current > RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Trop de requêtes - réessayez plus tard.")
