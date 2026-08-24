"""Vérifications de santé (Phase 19, §4). Fonctions pures autant que
possible - testables sans dépendre d'un vrai VPS ou d'une vraie base.
"""

import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Alert:
    check_name: str
    message: str


def check_module_freshness(
    module_name: str, last_event_time: datetime | None, now: datetime, max_age_seconds: int
) -> Alert | None:
    if last_event_time is None:
        return Alert(
            check_name=f"freshness.{module_name}",
            message=f"Aucun événement jamais reçu du module '{module_name}'.",
        )
    if (now - last_event_time) > timedelta(seconds=max_age_seconds):
        age_minutes = (now - last_event_time).total_seconds() / 60
        return Alert(
            check_name=f"freshness.{module_name}",
            message=f"Module '{module_name}' silencieux depuis {age_minutes:.1f} minutes.",
        )
    return None


def check_disk_space(path: str = "/", threshold_pct: float = 85.0) -> Alert | None:
    usage = shutil.disk_usage(path)
    used_pct = (usage.used / usage.total) * 100
    if used_pct >= threshold_pct:
        return Alert(
            check_name="disk_space",
            message=f"Espace disque utilisé : {used_pct:.1f}% (seuil : {threshold_pct}%).",
        )
    return None


def check_reconnection_rate(reconnection_count: int, window_minutes: int, max_allowed: int) -> Alert | None:
    if reconnection_count > max_allowed:
        return Alert(
            check_name="reconnection_rate",
            message=(
                f"{reconnection_count} reconnexions du collecteur en {window_minutes} minutes "
                f"(seuil : {max_allowed})."
            ),
        )
    return None


def check_kill_switch(active: bool) -> Alert | None:
    if active:
        return Alert(check_name="kill_switch", message="Le kill switch est actif - aucune nouvelle position.")
    return None
