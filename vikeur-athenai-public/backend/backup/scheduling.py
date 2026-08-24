"""Ordonnancement des sauvegardes (Module 2, §4.3). Fonction pure."""

from datetime import datetime, timedelta


def seconds_until_next_run(now: datetime, target_hour_utc: int = 3) -> float:
    """Retourne le nombre de secondes jusqu'à la prochaine occurrence de
    `target_hour_utc:00` UTC - aujourd'hui si l'heure n'est pas encore
    passée, sinon demain.
    """
    candidate = now.replace(hour=target_hour_utc, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return (candidate - now).total_seconds()
