"""Vocabulaire du Strategy Lifecycle (Étape 3 du plan validé le 16/08/2026).

Deux chemins distincts, jamais un seul axe linéaire :

Promotion (une stratégie qui n'a encore rien prouvé) :
    REGISTERED -> COLLECTING -> EXPERIMENTAL -> VALIDATED -> PRODUCTION

Éviction (une stratégie qui perd son edge) :
    UNDER_REVIEW -> DEGRADED -> SUSPENDED -> DEPRECATED

Une stratégie DEGRADED ou SUSPENDED n'est jamais définitivement morte -
`eviction_rules.determine_resurrection_transition` peut la repromouvoir
en EXPERIMENTAL si l'espérance nette redevient positive sur un nouvel
échantillon de signaux, sans jamais effacer l'historique de sa
dégradation (`strategy_lifecycle_history`, append-only).
"""

from __future__ import annotations

REGISTERED = "registered"
COLLECTING = "collecting"
EXPERIMENTAL = "experimental"
VALIDATED = "validated"
PRODUCTION = "production"

UNDER_REVIEW = "under_review"
DEGRADED = "degraded"
SUSPENDED = "suspended"
DEPRECATED = "deprecated"

ALL_STATUSES = frozenset(
    {
        REGISTERED,
        COLLECTING,
        EXPERIMENTAL,
        VALIDATED,
        PRODUCTION,
        UNDER_REVIEW,
        DEGRADED,
        SUSPENDED,
        DEPRECATED,
    }
)

# Statuts éligibles au mode réel (ADR-0014/0015, même principe de
# gouvernance que le Confidence Lifecycle : "un moteur non validé ne
# doit pas être traité comme s'il avait déjà démontré sa rentabilité",
# mandat §Principe 3). UNDER_REVIEW y reste inclus délibérément - la
# stratégie continue de trader pendant la surveillance renforcée (le
# Risk Engine est responsable de réduire sa taille de position, chantier
# séparé, non construit dans cette étape).
LIVE_ELIGIBLE_STATUSES = frozenset({VALIDATED, PRODUCTION, UNDER_REVIEW})

# Statuts qui ne contribuent jamais à la fusion, quel que soit le mode
# d'exécution. COLLECTING/REGISTERED : pas encore prouvés, jamais
# fusionnés (shadow mode). SUSPENDED/DEPRECATED : arrêt total. DEGRADED
# n'y figure volontairement PAS - il continue de trader en Paper (le
# mandat est explicite : "elle continue de tourner en Paper pour voir
# si elle se rétablit") ; seul le mode réel l'exclut, via
# LIVE_ELIGIBLE_STATUSES ci-dessus.
ALWAYS_EXCLUDED_FROM_FUSION_STATUSES = frozenset({REGISTERED, COLLECTING, SUSPENDED, DEPRECATED})

# Statuts pouvant faire l'objet d'une réévaluation d'éviction (assez
# "vivants" pour accumuler des trades réels/paper à mesurer).
EVICTION_ELIGIBLE_STATUSES = frozenset({EXPERIMENTAL, VALIDATED, PRODUCTION, UNDER_REVIEW, DEGRADED})

# Statuts pouvant faire l'objet d'une résurrection.
RESURRECTION_ELIGIBLE_STATUSES = frozenset({DEGRADED, SUSPENDED})

# Statut par défaut d'une stratégie déjà en production au moment où ce
# chantier est déployé (les 3 moteurs directionnels actifs et
# funding_basis_arbitrage) - EXPERIMENTAL reflète fidèlement leur
# réalité actuelle (autorisés à agir en Paper, pas encore validés
# statistiquement), sans supposer plus qu'on ne sait.
DEFAULT_STATUS_FOR_EXISTING_STRATEGY = EXPERIMENTAL
