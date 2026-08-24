"""Anti-spam (mandat §18, Étape 10 du plan validé le 16/08/2026) - un
Debouncer en mémoire, pas persisté : le service redémarre rarement, et
repartir sur un état vide après un redémarrage est un compromis
acceptable plutôt qu'une dépendance supplémentaire pour un simple
compteur de fenêtre glissante.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# Mandat : "Si la même erreur se reproduit dans les 15 minutes, l'alerte
# est mise en sourdine."
DEFAULT_DEBOUNCE_WINDOW = timedelta(minutes=15)


class Debouncer:
    def __init__(self, window: timedelta = DEFAULT_DEBOUNCE_WINDOW) -> None:
        self._window = window
        self._last_sent: dict[str, datetime] = {}

    def should_send(self, dedupe_key: str, now: datetime) -> bool:
        """Retourne `False` si `dedupe_key` a déjà été envoyé il y a
        moins de `window` - mémorise systématiquement le nouvel envoi
        (jamais un `should_send` répété sans effet de bord)."""
        last = self._last_sent.get(dedupe_key)
        if last is not None and (now - last) < self._window:
            return False
        self._last_sent[dedupe_key] = now
        return True

    def mark_resolved(self, dedupe_key: str) -> None:
        """Réinitialise la fenêtre pour cette clé - mandat : "Si l'erreur
        est résolue : 'WebSocket Reconnected...' -> Envoyé pour signaler
        la fin de la crise." Le prochain problème du même type doit
        pouvoir notifier immédiatement, pas hériter d'une fenêtre du
        problème précédent."""
        self._last_sent.pop(dedupe_key, None)
