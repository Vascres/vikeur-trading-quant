from datetime import UTC, datetime, timedelta

from monitoring.health_checks import (
    check_disk_space,
    check_kill_switch,
    check_module_freshness,
    check_reconnection_rate,
)


def test_freshness_alert_when_never_seen():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    alert = check_module_freshness("decision_engine", None, now, max_age_seconds=180)
    assert alert is not None
    assert "Aucun événement" in alert.message


def test_freshness_alert_when_stale():
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    last_event = now - timedelta(minutes=10)
    alert = check_module_freshness("decision_engine", last_event, now, max_age_seconds=180)
    assert alert is not None


def test_freshness_no_alert_when_fresh():
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    last_event = now - timedelta(seconds=30)
    alert = check_module_freshness("decision_engine", last_event, now, max_age_seconds=180)
    assert alert is None


def test_reconnection_rate_no_alert_below_threshold():
    assert check_reconnection_rate(3, window_minutes=15, max_allowed=5) is None


def test_reconnection_rate_alert_above_threshold():
    alert = check_reconnection_rate(8, window_minutes=15, max_allowed=5)
    assert alert is not None
    assert "8 reconnexions" in alert.message


def test_kill_switch_alert_when_active():
    assert check_kill_switch(True) is not None


def test_kill_switch_no_alert_when_inactive():
    assert check_kill_switch(False) is None


def test_disk_space_no_alert_when_below_threshold(monkeypatch):
    import shutil

    fake_usage = shutil.disk_usage.__class__ if False else None  # noqa: F841 (juste pour lisibilité)

    class FakeUsage:
        total = 1000
        used = 500
        free = 500

    monkeypatch.setattr(shutil, "disk_usage", lambda path: FakeUsage())
    assert check_disk_space(threshold_pct=85.0) is None


def test_disk_space_alert_when_above_threshold(monkeypatch):
    import shutil

    class FakeUsage:
        total = 1000
        used = 900
        free = 100

    monkeypatch.setattr(shutil, "disk_usage", lambda path: FakeUsage())
    alert = check_disk_space(threshold_pct=85.0)
    assert alert is not None
    assert "90.0%" in alert.message
