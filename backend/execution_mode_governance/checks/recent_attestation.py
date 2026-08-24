"""Prérequis générique : attestation humaine récente (ADR-0004/0008).

Limitation assumée et documentée : "kill switch testé" et "sauvegardes
vérifiées" n'ont aujourd'hui aucun mécanisme de détection automatique
fiable dans la plateforme - plutôt que d'inventer une fausse
automatisation, ces prérequis reposent sur une attestation humaine
explicite, nominative et horodatée (`governance_attestations`),
consultable et auditable comme n'importe quelle autre donnée de
gouvernance. Une même classe est réutilisée pour chaque clé
d'attestation plutôt que dupliquée (Development Standards §3, Open/Closed).
"""

from __future__ import annotations

from shared.governance_check import GovernanceCheck, GovernanceCheckResult, GovernanceContext

DEFAULT_MAX_ATTESTATION_AGE_DAYS = 30


class RecentAttestationCheck(GovernanceCheck):
    def __init__(
        self, attestation_key: str, label: str, max_age_days: int = DEFAULT_MAX_ATTESTATION_AGE_DAYS
    ) -> None:
        self.check_name = f"attestation_{attestation_key}"
        self._attestation_key = attestation_key
        self._label = label
        self._max_age_days = max_age_days

    def check(self, context: GovernanceContext) -> GovernanceCheckResult:
        attested_at = context.attestations.get(self._attestation_key)
        if attested_at is None:
            return GovernanceCheckResult(
                self.check_name, passed=False, reason=f"{self._label} : jamais attesté."
            )

        age_days = (context.evaluated_at - attested_at).total_seconds() / 86400
        if age_days > self._max_age_days:
            return GovernanceCheckResult(
                self.check_name,
                passed=False,
                reason=f"{self._label} : dernière attestation vieille de {age_days:.0f} jour(s), max {self._max_age_days}.",
            )

        return GovernanceCheckResult(self.check_name, passed=True)
