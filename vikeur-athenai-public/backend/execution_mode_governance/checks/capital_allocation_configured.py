"""Prérequis : une allocation de capital est explicitement configurée
pour chaque exchange actif (Étape 6, 16/08/2026, "Mur de Fer" - mandat
§10 : "vérification des limites de capital").

Le "mur d'allocation" (Étape 5, `capital_allocation_config`) protège déjà
chaque décision individuelle via `risk_engine` - ce prérequis empêche en
plus d'entrer en mode réel tant qu'aucun choix explicite d'allocation
n'a jamais été fait pour un exchange actif, plutôt que de laisser
`risk_engine` bloquer silencieusement chaque décision une par une après
coup (mandat §11 : "Le système ne doit jamais pouvoir dépasser cette
limite" - vérifié ici en amont, pas seulement en aval).
"""

from __future__ import annotations

from shared.governance_check import GovernanceCheck, GovernanceCheckResult, GovernanceContext


class CapitalAllocationConfiguredCheck(GovernanceCheck):
    check_name = "capital_allocation_configured"

    def check(self, context: GovernanceContext) -> GovernanceCheckResult:
        if context.capital_allocation_configured:
            return GovernanceCheckResult(self.check_name, passed=True)

        return GovernanceCheckResult(
            self.check_name,
            passed=False,
            reason=(
                "Aucune allocation de capital configurée pour au moins un exchange actif "
                "(capital_allocation_config) - choisir explicitement un pourcentage avant le mode réel."
            ),
        )
