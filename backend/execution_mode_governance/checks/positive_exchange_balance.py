"""Prérequis : le solde réel de chaque exchange actif est strictement
positif (Étape 6, 16/08/2026, "Mur de Fer" - mandat §10, Check 4 de la
conception validée : "Le solde de l'exchange est-il supérieur à 0 ?").

Un solde nul ou négatif rendrait le mode réel actif sans qu'aucune
position ne puisse jamais être ouverte (`PositionSizingRule` produirait
une quantité nulle) - démarrer le mode réel dans cet état masquerait un
compte non approvisionné derrière un statut "Live" trompeur, plutôt que
de le signaler clairement avant l'activation.
"""

from __future__ import annotations

from shared.governance_check import GovernanceCheck, GovernanceCheckResult, GovernanceContext


class PositiveExchangeBalanceCheck(GovernanceCheck):
    check_name = "positive_exchange_balance"

    def check(self, context: GovernanceContext) -> GovernanceCheckResult:
        if context.exchange_balance_positive:
            return GovernanceCheckResult(self.check_name, passed=True)

        return GovernanceCheckResult(
            self.check_name,
            passed=False,
            reason=(
                "Le solde réel d'au moins un exchange actif est nul, négatif, ou inconnu "
                "(portfolio_snapshots) - approvisionner le compte avant le mode réel."
            ),
        )
