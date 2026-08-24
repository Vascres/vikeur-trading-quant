"""Tests de l'API Backend (Phase 18).

Utilise le client de test FastAPI avec un pool DB/Redis mocké pour rester
rapide et indépendant d'une vraie base (les tests d'intégration bout-en-
bout sur base réelle restent couverts par test_migrations.py, Phase 6).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
import execution_mode_governance.main as governance


@pytest.fixture
def client(monkeypatch):
    # Configure et recharge l'authentification ici même - ne doit jamais
    # dépendre de l'ordre de collecte avec test_auth.py (bug préexistant :
    # API_AUTH_TOKEN n'est lu qu'une fois à l'import de shared.auth ;
    # sans ce rechargement, ces tests échouaient en 500 dès qu'ils
    # s'exécutaient avant test_auth.py, qui fait ce même rechargement
    # dans sa propre fixture).
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

    api_main.db_pool = fake_pool
    api_main.redis_client = fake_redis

    with TestClient(api_main.app) as test_client:
        test_client.headers["Authorization"] = "Bearer test-secret-token"
        yield test_client, fake_conn, fake_redis


def test_health(client):
    test_client, _, _ = client
    response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_kill_switch_inactive_by_default(client):
    test_client, _conn, fake_redis = client
    fake_redis.get.return_value = None

    response = test_client.get("/kill-switch")

    assert response.status_code == 200
    assert response.json() == {"active": False}


def test_set_kill_switch_active(client):
    """`lifespan` utilise toujours de vraies connexions (limitation
    architecturale préexistante de api/main.py - db_pool/redis_client ne
    sont pas réellement mockables une fois le TestClient démarré) : on
    vérifie donc l'effet réel via un second appel plutôt qu'un appel de
    mock qui ne correspondrait plus à ce qui s'exécute vraiment."""
    test_client, _conn, _redis = client

    response = test_client.post("/kill-switch", json={"active": True})
    assert response.status_code == 200
    assert response.json() == {"active": True}

    verify_response = test_client.get("/kill-switch")
    assert verify_response.json() == {"active": True}

    # Remet l'état à inactif pour ne pas polluer les tests suivants de ce
    # même processus (le kill switch réel est partagé entre les tests).
    test_client.post("/kill-switch", json={"active": False})


def test_get_positions_returns_empty_list(client):
    test_client, fake_conn, _redis = client
    fake_conn.fetch.return_value = []

    response = test_client.get("/positions")

    assert response.status_code == 200
    assert response.json() == []


def test_change_execution_mode_rejects_missing_confirmation(client, monkeypatch):
    """Vérifie que la route délègue bien la décision à
    execution_mode_governance plutôt que de dupliquer sa logique - un
    rejet de gouvernance doit se traduire par un 400, jamais un succès."""
    test_client, _conn, _redis = client

    async def fake_request_mode_change(
        db_pool, redis_client, target_mode, requested_by, confirmation_phrase, publish
    ):

        return governance.ModeChangeResult(
            accepted=False,
            new_mode=None,
            reason="Phrase de confirmation manquante ou incorrecte.",
            evaluation=None,
        )

    monkeypatch.setattr("api.main.governance.request_mode_change", fake_request_mode_change)

    response = test_client.post("/execution-mode", json={"target_mode": "real", "requested_by": "operateur"})

    assert response.status_code == 400


def test_change_execution_mode_accepts_valid_downgrade(client, monkeypatch):
    test_client, _conn, _redis = client

    async def fake_request_mode_change(
        db_pool, redis_client, target_mode, requested_by, confirmation_phrase, publish
    ):

        return governance.ModeChangeResult(accepted=True, new_mode="paper", reason=None, evaluation=None)

    monkeypatch.setattr("api.main.governance.request_mode_change", fake_request_mode_change)

    response = test_client.post("/execution-mode", json={"target_mode": "paper", "requested_by": "operateur"})

    assert response.status_code == 200
    assert response.json()["new_mode"] == "paper"


def test_record_governance_attestation(client):
    """`lifespan` utilise toujours de vraies connexions (même limitation
    que test_set_kill_switch_active ci-dessus) - la réponse 200 avec
    `recorded: True` suffit à prouver que l'insertion a réussi (une
    exception aurait produit un 500, jamais ce corps de réponse)."""
    test_client, _conn, _redis = client

    response = test_client.post(
        "/execution-mode/attestations",
        json={
            "key": "kill_switch_tested",
            "attested_by": "operateur",
            "notes": "Testé manuellement le 27/07",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"recorded": True, "key": "kill_switch_tested"}


def test_get_calibration_status_returns_none_when_no_run_exists(client):
    test_client, fake_conn, _redis = client
    fake_conn.fetchrow.return_value = None

    response = test_client.get("/calibration")

    assert response.status_code == 200
    assert response.json() == {"active_calibration": None, "latest_attempt": None}


# --- Étape 5 (16/08/2026) : mur d'allocation du capital réel ---


def test_get_capital_allocation_returns_latest_row_per_exchange(client):
    """Même limitation de fixture (connexion réelle, mock ignoré, cf.
    tests Paper ci-dessous) - auto-contenu via un POST réel suivi d'un GET."""
    test_client, _fake_conn, _redis = client

    post_response = test_client.post(
        "/capital-allocation", json={"exchange": "htx", "allocation_pct": 50.0, "set_by": "operateur"}
    )
    assert post_response.status_code == 200

    response = test_client.get("/capital-allocation")

    assert response.status_code == 200
    htx_row = next(r for r in response.json() if r["exchange"] == "htx")
    assert htx_row["allocation_pct"] == 50.0


def test_set_capital_allocation_rejects_value_above_100(client):
    test_client, _conn, _redis = client

    response = test_client.post(
        "/capital-allocation", json={"exchange": "htx", "allocation_pct": 150.0, "set_by": "operateur"}
    )

    assert response.status_code == 400


def test_set_capital_allocation_rejects_zero_or_negative(client):
    test_client, _conn, _redis = client

    response = test_client.post(
        "/capital-allocation", json={"exchange": "htx", "allocation_pct": 0.0, "set_by": "operateur"}
    )

    assert response.status_code == 400


def test_set_capital_allocation_accepts_valid_value(client):
    test_client, _conn, _redis = client

    response = test_client.post(
        "/capital-allocation", json={"exchange": "htx", "allocation_pct": 50.0, "set_by": "operateur"}
    )

    assert response.status_code == 200
    assert response.json() == {"exchange": "htx", "allocation_pct": 50.0}


# --- Étape 4 (16/08/2026) : capital virtuel du Paper Portfolio ---


def test_get_paper_capital_returns_the_migration_seeded_default_on_a_fresh_database(client):
    """Correctif du 17/08/2026 (trouvé en reproduisant l'échec CI réel,
    634 tests en cascade à cause d'un identifiant de révision Alembic
    trop long - cf. renommage des migrations 0020/0022/0024) : ce test
    affirmait qu'une base fraîchement migrée n'a AUCUNE ligne dans
    `paper_capital_config`, ce qui n'a jamais été vrai - la migration
    0022 sème elle-même une ligne par défaut (1000 USDT,
    `set_by='migration_default'`) au moment de sa création. Le
    comportement réel et voulu (paper trading utilisable dès le premier
    déploiement, sans configuration manuelle préalable) était correct ;
    c'est ce test qui affirmait un état impossible à atteindre."""
    test_client, fake_conn, _redis = client
    fake_conn.fetchrow.return_value = None  # sans effet - `lifespan` utilise toujours de vraies connexions

    response = test_client.get("/paper-capital")

    assert response.status_code == 200
    body = response.json()
    assert body["initial_capital"] == 1000.0
    assert body["reference_currency"] == "USDT"
    assert body["set_by"] == "migration_default"


def test_set_then_get_paper_capital_reflects_the_latest_value(client):
    """Même limitation de fixture que ci-dessus (connexion réelle, mock
    ignoré) - ce test reste donc auto-contenu : il pose une valeur via
    l'endpoint d'écriture réel, puis vérifie que la lecture reflète bien
    CETTE valeur (la plus récente par `set_at`), plutôt que de dépendre
    d'un mock qui ne s'applique pas réellement à cette route."""
    test_client, _fake_conn, _redis = client

    post_response = test_client.post("/paper-capital", json={"initial_capital": 777.0, "set_by": "operateur"})
    assert post_response.status_code == 200

    get_response = test_client.get("/paper-capital")
    assert get_response.status_code == 200
    assert get_response.json()["initial_capital"] == 777.0


def test_set_paper_capital_rejects_non_positive_value(client):
    test_client, _conn, _redis = client

    response = test_client.post("/paper-capital", json={"initial_capital": 0, "set_by": "operateur"})

    assert response.status_code == 400


def test_set_paper_capital_accepts_valid_value(client):
    test_client, _conn, _redis = client

    response = test_client.post("/paper-capital", json={"initial_capital": 350.0, "set_by": "operateur"})

    assert response.status_code == 200
    assert response.json() == {"initial_capital": 350.0, "market_type": "spot"}


# --- Deux pools Paper séparés par market_type (18/08/2026) ---


def test_paper_capital_futures_pool_is_independent_from_spot(client):
    """Poser une valeur sur le pool spot ne doit jamais affecter le pool
    futures, et inversement - vérifié en posant deux valeurs très
    différentes et en confirmant que chaque lecture reste isolée."""
    test_client, _conn, _redis = client

    spot_response = test_client.post(
        "/paper-capital", json={"initial_capital": 350.0, "set_by": "operateur", "market_type": "spot"}
    )
    assert spot_response.status_code == 200
    assert spot_response.json() == {"initial_capital": 350.0, "market_type": "spot"}

    futures_response = test_client.post(
        "/paper-capital",
        json={"initial_capital": 2000.0, "set_by": "operateur", "market_type": "futures_perpetual"},
    )
    assert futures_response.status_code == 200
    assert futures_response.json() == {"initial_capital": 2000.0, "market_type": "futures_perpetual"}

    spot_get = test_client.get("/paper-capital?market_type=spot")
    assert spot_get.json()["initial_capital"] == 350.0
    assert spot_get.json()["market_type"] == "spot"

    futures_get = test_client.get("/paper-capital?market_type=futures_perpetual")
    assert futures_get.json()["initial_capital"] == 2000.0
    assert futures_get.json()["market_type"] == "futures_perpetual"


def test_paper_capital_rejects_invalid_market_type(client):
    test_client, _conn, _redis = client

    response = test_client.post(
        "/paper-capital",
        json={"initial_capital": 100.0, "set_by": "operateur", "market_type": "spot_invalide"},
    )
    assert response.status_code == 400

    get_response = test_client.get("/paper-capital?market_type=inexistant")
    assert get_response.status_code == 400


# --- Frontend (16/08/2026) : statut Strategy Lifecycle ---


def test_get_strategies_lifecycle_returns_a_list(client):
    """`lifespan` utilise toujours de vraies connexions (même limitation
    documentée plus haut) - vérifie seulement que l'endpoint répond une
    liste, la table réelle étant vide dans cet environnement de test."""
    test_client, _fake_conn, _redis = client

    response = test_client.get("/strategies/lifecycle")

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_get_strategy_performance_metrics_returns_expected_shape_when_no_trades(client):
    test_client, _fake_conn, _redis = client

    response = test_client.get("/strategies/1/performance-metrics")

    assert response.status_code == 200
    body = response.json()
    assert body["strategy_id"] == 1
    assert body["trade_count"] == 0
    assert body["sharpe_ratio"] is None  # aucun trade -> aucune métrique inventée
    assert body["max_drawdown_pct"] is None


def test_get_why_no_trade_returns_the_nine_expected_funnel_stages(client):
    test_client, _fake_conn, _redis = client

    response = test_client.get("/why-no-trade")

    assert response.status_code == 200
    body = response.json()
    stage_names = [s["stage"] for s in body["funnel"]]
    assert stage_names == [
        "opinions_generated",
        "skipped_regime",
        "no_opinion",
        "excluded_lifecycle",
        "decisions_fused",
        "rejected_conviction",
        "passed_to_risk_engine",
        "rejected_risk_engine",
        "orders_executed",
    ]
    assert "cost_model_note" in body


def test_get_why_no_trade_accepts_execution_mode_and_since_hours(client):
    test_client, _fake_conn, _redis = client

    response = test_client.get("/why-no-trade?execution_mode=real&since_hours=48")

    assert response.status_code == 200
    assert response.json()["execution_mode"] == "real"
