"""Tests de notifications.rate_limiter (mandat §18, Étape 10, 16/08/2026)."""

from __future__ import annotations

from datetime import datetime, timedelta

from notifications.rate_limiter import Debouncer


def test_first_send_is_always_allowed():
    debouncer = Debouncer(window=timedelta(minutes=15))
    assert debouncer.should_send("ws_disconnected", datetime(2026, 8, 16, 12, 0)) is True


def test_repeated_send_within_window_is_suppressed():
    debouncer = Debouncer(window=timedelta(minutes=15))
    now = datetime(2026, 8, 16, 12, 0)
    debouncer.should_send("ws_disconnected", now)
    assert debouncer.should_send("ws_disconnected", now + timedelta(minutes=5)) is False


def test_send_allowed_again_after_window_elapses():
    debouncer = Debouncer(window=timedelta(minutes=15))
    now = datetime(2026, 8, 16, 12, 0)
    debouncer.should_send("ws_disconnected", now)
    assert debouncer.should_send("ws_disconnected", now + timedelta(minutes=16)) is True


def test_different_keys_never_interfere_with_each_other():
    debouncer = Debouncer(window=timedelta(minutes=15))
    now = datetime(2026, 8, 16, 12, 0)
    debouncer.should_send("ws_disconnected", now)
    assert debouncer.should_send("cost_model.cycle_error", now) is True


def test_mark_resolved_allows_immediate_resend():
    """Mandat : la fin d'une crise doit pouvoir notifier immédiatement,
    sans hériter de la fenêtre du problème qui vient de se résoudre."""
    debouncer = Debouncer(window=timedelta(minutes=15))
    now = datetime(2026, 8, 16, 12, 0)
    debouncer.should_send("ws_disconnected", now)
    debouncer.mark_resolved("ws_disconnected")
    assert debouncer.should_send("ws_disconnected", now + timedelta(seconds=1)) is True
