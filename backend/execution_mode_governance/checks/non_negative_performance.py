"""Prérequis : performance non négative sur le mode courant (ADR-0004/0008).

Limitation assumée et documentée : ce prérequis est volontairement
simpliste (P&L réalisé cumulé >= seuil configurable, 0 par défaut) tant
que la couche de calibration probabiliste et le méta-moteur (chantiers
futurs de l'architecture cible, §3.3) ne fournissent pas de métriques
statistiquement plus riches (Sharpe, Brier score...). Remplacer ce
prérequis par des métriques plus robustes est un changement de contrat
qui devra faire l'objet de son propre ADR le moment venu - pas une
modification silencieuse de ce fichier.
"""

from __future__ import annotations

from decimal import Decimal

from shared.governance_check import GovernanceCheck, GovernanceCheckResult, GovernanceContext

DEFAULT_MINIMUM_REALIZED_PNL = Decimal("0")


class NonNegativePerformanceCheck(GovernanceCheck):
    check_name = "non_negative_performance"

    def __init__(self, minimum_realized_pnl: Decimal = DEFAULT_MINIMUM_REALIZED_PNL) -> None:
        self._minimum_realized_pnl = minimum_realized_pnl

    def check(self, context: GovernanceContext) -> GovernanceCheckResult:
        if context.realized_pnl_since_mode_start >= self._minimum_realized_pnl:
            return GovernanceCheckResult(self.check_name, passed=True)

        return GovernanceCheckResult(
            self.check_name,
            passed=False,
            reason=(
                f"P&L réalisé cumulé depuis le début du mode '{context.current_mode}' : "
                f"{context.realized_pnl_since_mode_start}, minimum requis {self._minimum_realized_pnl}."
            ),
        )
