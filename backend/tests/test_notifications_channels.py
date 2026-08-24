"""Tests de notifications.channels (mandat §18, Étape 10, 16/08/2026)."""

from __future__ import annotations

from notifications.channels import Channel, route


def test_started_events_are_never_notified():
    assert route("cost_model.started", "cost_model", {}) is None


def test_unknown_event_without_alert_pattern_is_never_notified():
    """Repli sûr : un événement inconnu et non reconnu comme une alerte
    n'est jamais notifié plutôt que de spammer un canal par défaut."""
    assert route("cost_model.run_completed", "cost_model", {}) is None


# --- Gabarits explicites ---


def test_kill_switch_activated_routes_to_alerts_critical_never_debounced():
    notification = route("kill_switch.activated", "api", {"active": True})
    assert notification.channel == Channel.ALERTS
    assert notification.critical is True
    assert notification.should_debounce is False
    assert "KILL SWITCH" in notification.text


def test_mode_changed_to_real_is_critical():
    notification = route(
        "execution_mode_governance.mode_changed", "execution_mode_governance", {"new_mode": "real"}
    )
    assert notification.critical is True


def test_mode_changed_to_paper_is_not_critical():
    notification = route(
        "execution_mode_governance.mode_changed", "execution_mode_governance", {"new_mode": "paper"}
    )
    assert notification.critical is False


def test_strategy_transition_to_suspended_is_critical():
    notification = route(
        "strategy_lifecycle.transition",
        "strategy_lifecycle",
        {"strategy_id": 3, "new_status": "suspended", "reason": "EV négative"},
    )
    assert notification.channel == Channel.ALERTS
    assert notification.critical is True
    assert "SUSPENDED" in notification.text
    assert notification.should_debounce is False  # jamais mis en sourdine, toujours notifié


def test_strategy_transition_to_experimental_is_not_critical():
    """Une repromotion (résurrection) reste une bonne nouvelle, pas une alerte sonore."""
    notification = route(
        "strategy_lifecycle.transition",
        "strategy_lifecycle",
        {"strategy_id": 3, "new_status": "experimental", "reason": "résurrection"},
    )
    assert notification.critical is False


def test_dedupe_key_for_strategy_transition_is_scoped_per_strategy():
    """Deux stratégies différentes ne doivent jamais se supprimer
    mutuellement au niveau du rate limiter."""
    a = route(
        "strategy_lifecycle.transition", "strategy_lifecycle", {"strategy_id": 1, "new_status": "degraded"}
    )
    b = route(
        "strategy_lifecycle.transition", "strategy_lifecycle", {"strategy_id": 2, "new_status": "degraded"}
    )
    assert a.dedupe_key != b.dedupe_key


def test_stop_loss_placement_failed_is_critical_alert():
    notification = route(
        "execution_engine.futures_stop_loss_placement_failed",
        "execution_engine",
        {"symbol": "ETH/USDT", "position_id": 42},
    )
    assert notification.channel == Channel.ALERTS
    assert notification.critical is True
    assert "SANS PROTECTION" in notification.text


def test_order_executed_in_real_mode_routes_to_live_channel():
    notification = route(
        "execution_engine.order_executed",
        "execution_engine",
        {"symbol": "BTC/USDT", "side": "buy", "quantity": "0.01", "price": "60000", "execution_mode": "real"},
    )
    assert notification.channel == Channel.LIVE
    assert "🟢" in notification.text
    assert notification.should_debounce is False


def test_order_executed_in_paper_mode_routes_to_paper_channel():
    notification = route(
        "execution_engine.order_executed",
        "execution_engine",
        {
            "symbol": "BTC/USDT",
            "side": "sell",
            "quantity": "0.01",
            "price": "60000",
            "execution_mode": "paper",
        },
    )
    assert notification.channel == Channel.PAPER
    assert "🔵" in notification.text


def test_multiple_order_executed_events_never_share_a_dedupe_key_effect():
    """Chaque trade est un événement distinct - vérifie que le
    should_debounce reste False (jamais fusionné avec un trade précédent),
    même si le dedupe_key (event_type seul) est identique entre deux trades."""
    notification = route(
        "execution_engine.order_executed",
        "execution_engine",
        {"symbol": "ETH/USDT", "side": "buy", "quantity": "0.05", "price": "3000", "execution_mode": "real"},
    )
    assert notification.should_debounce is False


# --- Repli générique par motif ---


def test_generic_error_pattern_falls_back_to_alerts():
    notification = route("calibration.cycle_error", "calibration", {"error": "timeout"})
    assert notification.channel == Channel.ALERTS
    assert notification.should_debounce is True  # motif générique -> peut être mis en sourdine


def test_generic_disconnected_pattern_falls_back_to_alerts():
    notification = route("collector.ws_disconnected", "data_collector", {"exchange": "htx"})
    assert notification.channel == Channel.ALERTS


def test_generic_pattern_never_crashes_on_missing_payload_fields():
    """Le repli générique ne doit jamais lever à cause d'un champ
    manquant - contrairement aux gabarits explicites, il n'accède à
    aucune clé précise du payload."""
    notification = route("portfolio_aggregator.reconciliation_discrepancy_detected", "portfolio", {})
    assert notification is not None
    assert notification.channel == Channel.ALERTS


# --- Consolidation monitoring (16/08/2026) : monitoring.alert_triggered ---


def test_monitoring_alert_routes_to_alerts_and_is_never_debounced_twice():
    """`monitoring` applique déjà son propre cooldown par check_name en
    amont (Redis, 30 min) - notifications ne doit jamais superposer une
    seconde mise en sourdine par-dessus."""
    notification = route(
        "monitoring.alert_triggered",
        "monitoring",
        {"check_name": "freshness.decision_engine", "message": "Module silencieux depuis 10 minutes."},
    )
    assert notification.channel == Channel.ALERTS
    assert notification.critical is True
    assert notification.should_debounce is False
    assert "silencieux" in notification.text


def test_monitoring_alert_dedupe_key_is_scoped_per_check_name():
    a = route("monitoring.alert_triggered", "monitoring", {"check_name": "disk_space", "message": "..."})
    b = route(
        "monitoring.alert_triggered", "monitoring", {"check_name": "freshness.risk_engine", "message": "..."}
    )
    assert a.dedupe_key != b.dedupe_key
