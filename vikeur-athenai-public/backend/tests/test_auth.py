"""Tests du Module 1 : authentification et limitation de débit."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

import api.main as api_main


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("API_AUTH_TOKEN", "test-secret-token")
    import importlib

    import shared.auth as auth_module

    importlib.reload(auth_module)
    api_main.verify_token = auth_module.verify_token

    fake_pool = MagicMock()
    fake_conn = AsyncMock()
    fake_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    fake_redis = AsyncMock()
    fake_redis.incr.return_value = 1

    api_main.db_pool = fake_pool
    api_main.redis_client = fake_redis

    with TestClient(api_main.app) as test_client:
        yield test_client, fake_conn, fake_redis


def test_health_never_requires_auth(client):
    test_client, _, _ = client
    response = test_client.get("/health")
    assert response.status_code == 200


def test_protected_route_without_token_is_rejected(client):
    test_client, _, _ = client
    response = test_client.get("/decisions")
    assert response.status_code == 401


def test_protected_route_with_wrong_token_is_rejected(client):
    test_client, _, _ = client
    response = test_client.get("/decisions", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401


def test_protected_route_with_correct_token_succeeds(client):
    test_client, fake_conn, _ = client
    fake_conn.fetch.return_value = []
    response = test_client.get("/decisions", headers={"Authorization": "Bearer test-secret-token"})
    assert response.status_code == 200


def test_kill_switch_post_requires_auth(client):
    test_client, _, _ = client
    response = test_client.post("/kill-switch", json={"active": True})
    assert response.status_code == 401


def test_rate_limit_blocks_after_threshold(client):
    """`lifespan` utilise toujours de vraies connexions (limitation
    architecturale préexistante, cf. test_api.py) - on déclenche donc la
    limite avec de vraies requêtes plutôt qu'un retour de mock qui ne
    correspondrait plus à ce qui s'exécute vraiment."""
    test_client, fake_conn, _redis = client
    fake_conn.fetch.return_value = []

    last_response = None
    for _ in range(35):  # au-dessus du seuil par défaut (30/minute)
        last_response = test_client.get("/decisions", headers={"Authorization": "Bearer test-secret-token"})
        if last_response.status_code == 429:
            break

    assert last_response.status_code == 429
