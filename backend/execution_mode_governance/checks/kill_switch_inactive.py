"""Prérequis : le Kill Switch global est désactivé (Étape 6, 16/08/2026,
"Mur de Fer" - mandat §10 : "vérification du Kill Switch").

Distinct de `RecentAttestationCheck("kill_switch_tested", ...)` : ce
dernier vérifie qu'un humain a TESTÉ le kill switch récemment, celui-ci
vérifie qu'il n'est PAS ACTIF maintenant - un kill switch actif interdit
structurellement toute nouvelle exécution (`shared/risk_rule.py`,
`KillSwitchRule`), donc démarrer le mode réel avec le kill switch enclenché
n'aurait aucun sens : le système serait "actif" sans jamais pouvoir agir,
ce qui masquerait un vrai problème derrière un état Live trompeur.
"""

from __future__ import annotations

from shared.governance_check import GovernanceCheck, GovernanceCheckResult, GovernanceContext


class KillSwitchInactiveCheck(GovernanceCheck):
    check_name = "kill_switch_inactive"

    def check(self, context: GovernanceContext) -> GovernanceCheckResult:
        if not context.kill_switch_active:
            return GovernanceCheckResult(self.check_name, passed=True)

        return GovernanceCheckResult(
            self.check_name,
            passed=False,
            reason="Le Kill Switch global est actif - le désactiver avant de passer en mode réel.",
        )
