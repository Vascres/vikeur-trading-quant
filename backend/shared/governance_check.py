"""Contrat GovernanceCheck (ADR-0004, ADR-0008 ; API Contracts Spec).

Miroir délibéré de `shared/risk_rule.py` : chaque prérequis d'activation
d'un mode d'exécution à risque supérieur (aujourd'hui, uniquement la
transition vers `real` - cf. execution_mode_governance/main.py) est une
règle indépendante et testable en isolation, évaluée sur un contexte
déjà assemblé par l'appelant. Une règle de gouvernance reste pure une
fois le contexte fourni - elle ne requête jamais la base elle-même.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class GovernanceContext:
    target_mode: str
    current_mode: str

    # Horodatage auquel ce contexte a été assemblé - injecté comme
    # donnée par l'appelant, jamais lu directement par une règle (une
    # règle qui appellerait l'horloge elle-même romprait le contrat de
    # pureté déjà respecté par Feature/Strategy/RiskRule).
    evaluated_at: datetime

    # Durée continue passée dans le mode courant (utile pour vérifier une
    # durée minimale de paper trading avant le passage en réel).
    continuous_mode_duration_seconds: float

    trade_count_since_mode_start: int
    realized_pnl_since_mode_start: Decimal

    # None si aucun instantané de portefeuille n'existe pour l'exchange
    # concerné (cf. ADR-0007) - un prérequis peut alors échouer plutôt
    # que de supposer une valeur par défaut.
    portfolio_snapshot_age_seconds: float | None

    # Dernière attestation humaine par clé (ex. "kill_switch_tested",
    # "backups_verified", "monitoring_active") - None si jamais attestée.
    # Une attestation manuelle, horodatée et nominative, tant qu'une
    # détection automatique fiable n'existe pas pour ce prérequis
    # (limitation assumée, documentée en ADR-0008).
    attestations: dict[str, datetime | None] = field(default_factory=dict)

    # Étape 6 (16/08/2026, "Mur de Fer") - quatre nouveaux prérequis.
    # Défauts volontairement du côté sûr (bloquant) : un appelant qui
    # oublierait de peupler l'un de ces champs bloque le passage en réel
    # plutôt que de l'autoriser silencieusement (principe directeur 3 :
    # jamais une hypothèse par défaut permissive sur un état inconnu).

    # Kill switch lu depuis Redis (`risk:kill_switch`) - True par défaut
    # (bloquant) tant qu'il n'a pas été explicitement vérifié inactif.
    kill_switch_active: bool = True

    # Au moins une ligne `capital_allocation_config` existe pour CHAQUE
    # exchange actif (ADR-0012) - False par défaut (bloquant).
    capital_allocation_configured: bool = False

    # Solde réel total (dernier instantané) strictement positif pour
    # CHAQUE exchange actif - False par défaut (bloquant).
    exchange_balance_positive: bool = False

    # Au moins une stratégie a le statut VALIDATED ou PRODUCTION
    # (Strategy Lifecycle, Étape 3) - False par défaut (bloquant). Le
    # prérequis "crucial" du mandat : "Si aucune stratégie n'est
    # validée mathématiquement, le mode Live est interdit de démarrage."
    has_live_eligible_strategy: bool = False


@dataclass(frozen=True)
class GovernanceCheckResult:
    check_name: str
    passed: bool
    reason: str | None = None


class GovernanceCheck(ABC):
    check_name: str

    @abstractmethod
    def check(self, context: GovernanceContext) -> GovernanceCheckResult:
        raise NotImplementedError
