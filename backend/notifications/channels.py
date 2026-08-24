"""Routage et mise en forme des événements journalisés vers les canaux
Telegram (mandat §18, Étape 10 du plan validé le 16/08/2026).

Trois canaux (mandat) :
- ALERTS : erreurs, refus, dégradations, Kill Switch - notifications
  sonores actives, "j'active les notifications sonores uniquement pour
  ce canal".
- LIVE : cycle de vie d'un trade réel.
- PAPER : cycle de vie d'un trade simulé, "le laboratoire".

Fonction pure - aucun accès réseau/DB/horloge (l'horloge du debounce
reste la responsabilité de l'appelant, `notifications/main.py`), testée
en isolation.

Le routage combine des gabarits explicites pour les événements les plus
importants du mandat (Kill Switch, changement de mode, transition de
lifecycle, trade exécuté, échec de stop-loss) et un repli générique par
motif de nom (`_ALERT_PATTERNS`) pour tout le reste - un nouvel
événement suivant la convention `<module>.<verbe>_error/failed/rejected`
est automatiquement classé en ALERTS sans modification de ce fichier
(mieux vaut sur-notifier une alerte inconnue que la manquer
silencieusement)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Channel(str, Enum):
    ALERTS = "alerts"
    LIVE = "live"
    PAPER = "paper"


@dataclass(frozen=True)
class RoutedNotification:
    channel: Channel
    text: str
    critical: bool  # notification sonore (mandat : réservée au canal Alerts)
    dedupe_key: str
    should_debounce: bool  # False pour les événements métier rares (jamais mis en sourdine)


# Jamais notifiés - bruit de routine au démarrage de chaque service
# (mandat : "Le système doit éviter le spam").
_IGNORED_SUFFIXES = (".started",)

# Motifs suffisants pour classer un événement en ALERTS sans gabarit
# dédié - couvre la longue traîne des ~60 types d'événements du dépôt
# sans les énumérer un par un.
_ALERT_PATTERNS = (
    "_error",
    "failed",
    "_rejected",
    "rejected",
    "disconnected",
    "stale",
    "discrepancy",
    "gap_detected",
    "without_stop_loss_capability",
)


def _humanize(event_type: str) -> str:
    return event_type.replace("_", " ").replace(".", " - ")


def route(event_type: str, source_module: str, payload: dict) -> RoutedNotification | None:
    if event_type.endswith(_IGNORED_SUFFIXES):
        return None

    if event_type == "kill_switch.activated":
        return RoutedNotification(
            Channel.ALERTS, "🛑 KILL SWITCH ACTIVÉ\nTrading arrêté.", True, event_type, False
        )
    if event_type == "kill_switch.deactivated":
        return RoutedNotification(
            Channel.ALERTS,
            "✅ Kill Switch désactivé\nTrading de nouveau autorisé.",
            False,
            event_type,
            False,
        )

    if event_type == "execution_mode_governance.mode_changed":
        new_mode = payload.get("new_mode", "?")
        return RoutedNotification(
            Channel.ALERTS,
            f"⚙️ Mode d'exécution changé : {new_mode}",
            new_mode == "real",
            event_type,
            False,
        )
    if event_type == "execution_mode_governance.change_rejected":
        return RoutedNotification(
            Channel.ALERTS,
            f"🚫 Passage en mode réel refusé\nRaison : {payload.get('reason', 'inconnue')}",
            False,
            event_type,
            False,
        )

    if event_type == "strategy_lifecycle.transition":
        new_status = payload.get("new_status", "?")
        strategy_id = payload.get("strategy_id", "?")
        critical = new_status in ("degraded", "suspended")
        emoji = "🔴" if critical else "🟡"
        return RoutedNotification(
            Channel.ALERTS,
            f"{emoji} STRATÉGIE {str(new_status).upper()} | ID {strategy_id}\n"
            f"Raison : {payload.get('reason', 'non précisée')}",
            critical,
            f"strategy_lifecycle.transition:{strategy_id}",
            False,  # une transition n'est jamais un doublon à mettre en sourdine, toujours notifiée
        )

    if event_type == "execution_engine.futures_stop_loss_placement_failed":
        position_id = payload.get("position_id", "?")
        return RoutedNotification(
            Channel.ALERTS,
            f"🛑 Échec de pose du stop-loss | {payload.get('symbol', '?')}\n"
            f"Position {position_id} SANS PROTECTION - vérification manuelle requise.",
            True,
            f"{event_type}:{position_id}",
            False,
        )
    if event_type == "execution_engine.futures_position_without_stop_loss_capability":
        return RoutedNotification(
            Channel.ALERTS,
            f"⚠️ Aucune capacité de stop-loss automatique sur cet exchange | "
            f"{payload.get('exchange', '?')}/{payload.get('symbol', '?')}",
            True,
            event_type,
            True,  # capacité manquante = état stable, pas la peine de le répéter en boucle
        )

    if event_type == "monitoring.alert_triggered":
        # Correctif du 16/08/2026 : consolidation de l'ancien envoi
        # direct de `monitoring/alerting.py` (retiré) - `monitoring` gère
        # déjà son propre anti-spam par check_name (cooldown Redis 30
        # min, cf. `monitoring/main.py::_send_if_not_in_cooldown`), donc
        # `should_debounce=False` ici pour ne jamais superposer une
        # seconde couche de mise en sourdine à celle déjà appliquée en amont.
        return RoutedNotification(
            Channel.ALERTS,
            f"🚨 {payload.get('message', event_type)}",
            True,
            f"monitoring:{payload.get('check_name', event_type)}",
            False,
        )

    if event_type == "execution_engine.order_executed":
        mode = payload.get("execution_mode", "paper")
        channel = Channel.LIVE if mode == "real" else Channel.PAPER
        emoji = "🟢" if channel == Channel.LIVE else "🔵"
        side = str(payload.get("side", "?")).upper()
        return RoutedNotification(
            channel,
            f"{emoji} ORDRE EXÉCUTÉ | {payload.get('symbol', '?')}\n"
            f"{side} {payload.get('quantity', '?')} @ {payload.get('price', '?')} "
            f"({payload.get('market_type', 'spot')})",
            False,
            event_type,
            False,  # chaque trade est un événement distinct, jamais un doublon à fusionner
        )

    if any(pattern in event_type for pattern in _ALERT_PATTERNS):
        return RoutedNotification(
            Channel.ALERTS,
            f"⚠️ {_humanize(event_type)} ({source_module})\n{payload}",
            False,
            event_type,
            True,
        )

    return None
