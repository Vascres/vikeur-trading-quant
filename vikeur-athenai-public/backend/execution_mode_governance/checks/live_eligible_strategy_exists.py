"""Prérequis "crucial" (mandat §10, Check 5 de la conception validée) :
au moins une stratégie a le statut VALIDATED ou PRODUCTION (Strategy
Lifecycle, Étape 3) avant que le mode réel puisse démarrer.

Citation directe du mandat : "Si aucune stratégie n'est validée
mathématiquement, le mode Live est interdit de démarrage." C'est la
jonction concrète entre le Strategy Lifecycle Manager (Étape 3) et le
Mur de Fer (Étape 6) - sans ce prérequis, un opérateur pourrait activer
le mode réel alors qu'aucun moteur n'a jamais démontré d'espérance nette
positive, ce que le reste de l'architecture (decision_engine, Étape 3)
empêche déjà décision par décision, mais pas encore au niveau du
passage de mode lui-même.
"""

from __future__ import annotations

from shared.governance_check import GovernanceCheck, GovernanceCheckResult, GovernanceContext


class LiveEligibleStrategyExistsCheck(GovernanceCheck):
    check_name = "live_eligible_strategy_exists"

    def check(self, context: GovernanceContext) -> GovernanceCheckResult:
        if context.has_live_eligible_strategy:
            return GovernanceCheckResult(self.check_name, passed=True)

        return GovernanceCheckResult(
            self.check_name,
            passed=False,
            reason=(
                "Aucune stratégie au statut VALIDATED ou PRODUCTION (strategy_lifecycle_state) - "
                "le mode réel est interdit tant qu'aucun moteur n'a démontré d'espérance nette positive."
            ),
        )
