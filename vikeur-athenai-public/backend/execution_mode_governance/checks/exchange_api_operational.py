"""Prérequis : l'API de l'exchange est opérationnelle (ADR-0004/0008).

Réutilise directement le signal déjà produit par le portefeuille réel
(ADR-0003/0007) plutôt que d'inventer une nouvelle sonde de connectivité
- un instantané de portefeuille récent est déjà la preuve que l'API de
l'exchange répond correctement (Data Governance Spec §1 : ne jamais
dupliquer une source de vérité déjà établie).
"""

from __future__ import annotations

from shared.governance_check import GovernanceCheck, GovernanceCheckResult, GovernanceContext

DEFAULT_MAX_SNAPSHOT_AGE_SECONDS = 300


class ExchangeApiOperationalCheck(GovernanceCheck):
    check_name = "exchange_api_operational"

    def __init__(self, max_snapshot_age_seconds: int = DEFAULT_MAX_SNAPSHOT_AGE_SECONDS) -> None:
        self._max_snapshot_age_seconds = max_snapshot_age_seconds

    def check(self, context: GovernanceContext) -> GovernanceCheckResult:
        age = context.portfolio_snapshot_age_seconds
        if age is None:
            return GovernanceCheckResult(
                self.check_name, passed=False, reason="Aucun instantané de portefeuille disponible."
            )
        if age > self._max_snapshot_age_seconds:
            return GovernanceCheckResult(
                self.check_name,
                passed=False,
                reason=f"Dernier instantané de portefeuille vieux de {age:.0f}s (max {self._max_snapshot_age_seconds}s).",
            )
        return GovernanceCheckResult(self.check_name, passed=True)
