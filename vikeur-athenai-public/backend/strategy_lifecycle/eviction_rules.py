"""Règles d'éviction et de résurrection (Étape 3 du plan validé le
16/08/2026) - fonctions pures, testées en isolation.

Les seuils ci-dessous sont les "Hard Limits pour un compte de 350 $"
tels que spécifiés dans le mandat - valeurs de départ prudentes, comme
chaque autre seuil de ce projet, à recalibrer une fois suffisamment de
transitions réelles observées.
"""

from __future__ import annotations

from decimal import Decimal

from strategy_lifecycle.metrics import LifecycleMetrics
from strategy_lifecycle.states import (
    DEGRADED,
    EVICTION_ELIGIBLE_STATUSES,
    EXPERIMENTAL,
    RESURRECTION_ELIGIBLE_STATUSES,
    UNDER_REVIEW,
)

# Aucune décision d'éviction sous ce seuil - une série de pertes sur un
# petit échantillon peut être du bruit statistique normal, pas une
# dégradation réelle (mandat : "Nous ne devons pas suspendre une
# stratégie à cause de la variance normale"). Même valeur que
# `shared.confidence_lifecycle.MIN_SAMPLE_VALIDATED` (30) - cohérence
# volontaire entre les deux notions de maturité statistique du projet,
# pas une coïncidence.
MIN_SAMPLE_FOR_EVICTION = 30

# Perte cumulée d'un agent au-delà de cette fraction du capital de
# référence -> DEGRADED immédiat (saute UNDER_REVIEW, mandat : "Passage
# immédiat en DEGRADED").
MAX_DRAWDOWN_FRACTION = Decimal("0.05")

# Sous ce seuil, la stratégie perd son edge face au bruit du marché
# (mandat : "le système perd son edge face au bruit du marché").
MIN_PROFIT_FACTOR = 1.1

# Résurrection : échantillon de quarantaine minimum et espérance nette
# minimale pour repromouvoir une stratégie DEGRADED/SUSPENDED (mandat
# §4 "La Mécanique de Résurrection").
MIN_QUARANTINE_SAMPLE = 50
MIN_RESURRECTION_EV_BPS = 40.0


def determine_eviction_transition(
    current_status: str,
    metrics: LifecycleMetrics,
    allocated_capital: Decimal,
) -> tuple[str, str] | None:
    """Retourne `(nouveau_statut, raison)` si une transition d'éviction
    est justifiée par les métriques fournies, sinon `None` (aucun
    changement). Ne s'applique qu'aux statuts déjà actifs en trading
    (`EVICTION_ELIGIBLE_STATUSES`) - REGISTERED/COLLECTING/SUSPENDED/
    DEPRECATED ne sont jamais réévalués ici (la résurrection depuis
    SUSPENDED/DEGRADED est une fonction séparée,
    `determine_resurrection_transition`).

    `allocated_capital` : capital de référence pour le calcul du
    drawdown - en l'absence d'une allocation par stratégie encore
    construite (Étape 5 du plan, "Dual Portfolio"), le capital total du
    portefeuille sert de repli documenté ; à remplacer par une
    allocation réelle par stratégie une fois ce chantier livré (limitation
    assumée, pas cachée)."""
    if current_status not in EVICTION_ELIGIBLE_STATUSES:
        return None
    if metrics.sample_size < MIN_SAMPLE_FOR_EVICTION:
        return None

    if allocated_capital > 0 and metrics.cumulative_pnl < 0:
        drawdown_fraction = -metrics.cumulative_pnl / allocated_capital
        if drawdown_fraction >= MAX_DRAWDOWN_FRACTION:
            if current_status == DEGRADED:
                return None  # déjà DEGRADED, pas de nouvelle transition à ce palier
            return DEGRADED, (
                f"Perte cumulée ({metrics.cumulative_pnl:.2f}) dépasse "
                f"{MAX_DRAWDOWN_FRACTION:.0%} du capital de référence "
                f"({allocated_capital:.2f}) sur {metrics.sample_size} trades."
            )

    unhealthy_ev = metrics.ev_net_bps is not None and metrics.ev_net_bps < 0
    unhealthy_profit_factor = metrics.profit_factor is not None and metrics.profit_factor < MIN_PROFIT_FACTOR
    if unhealthy_ev or unhealthy_profit_factor:
        if current_status in (UNDER_REVIEW, DEGRADED):
            return None  # déjà sous surveillance ou pire, pas de nouvelle transition à ce palier
        reasons = []
        if unhealthy_ev:
            reasons.append(f"espérance nette négative ({metrics.ev_net_bps:.2f} bps)")
        if unhealthy_profit_factor:
            reasons.append(f"profit factor sous le seuil ({metrics.profit_factor:.2f} < {MIN_PROFIT_FACTOR})")
        return UNDER_REVIEW, " et ".join(reasons) + f" sur {metrics.sample_size} trades."

    return None


def determine_resurrection_transition(
    current_status: str,
    quarantine_metrics: LifecycleMetrics,
) -> tuple[str, str] | None:
    """`quarantine_metrics` doit être calculé sur les trades survenus
    STRICTEMENT DEPUIS la dernière transition (pas l'historique complet,
    qui inclut la période ayant justifié la dégradation) - responsabilité
    de l'appelant (`strategy_lifecycle/repository.py`, paramètre `since`).

    Limitation assumée : pour une stratégie SUSPENDED, aucun trade réel
    ou paper n'est généré tant que le mécanisme de "signaux virtuels en
    quarantaine" (mandat §4) n'est pas construit (chantier ultérieur) -
    cette fonction reste correcte et testée, mais son chemin de
    résurrection restera inerte pour SUSPENDED tant que cette donnée
    n'existe pas. Pour DEGRADED, le chemin est déjà fonctionnel
    aujourd'hui : une stratégie DEGRADED continue de trader en Paper
    (cf. `strategy_lifecycle.states.ALWAYS_EXCLUDED_FROM_FUSION_STATUSES`),
    donc `quarantine_metrics` y reflète de vrais trades paper."""
    if current_status not in RESURRECTION_ELIGIBLE_STATUSES:
        return None
    if quarantine_metrics.sample_size < MIN_QUARANTINE_SAMPLE:
        return None
    if quarantine_metrics.ev_net_bps is not None and quarantine_metrics.ev_net_bps > MIN_RESURRECTION_EV_BPS:
        return EXPERIMENTAL, (
            f"Espérance nette redevenue positive ({quarantine_metrics.ev_net_bps:.2f} bps) "
            f"sur {quarantine_metrics.sample_size} signaux de quarantaine - repromu en {EXPERIMENTAL}."
        )
    return None
