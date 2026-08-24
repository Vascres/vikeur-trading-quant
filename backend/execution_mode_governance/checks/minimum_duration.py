"""Prérequis : durée minimale continue dans le mode courant (ADR-0004/0008).

Paramètre configurable et documenté (Development Standards §1) - jamais
codé en dur sans justification. La valeur par défaut (30 jours) est une
première estimation raisonnable, à ajuster par ADR si l'expérience
opérationnelle le justifie.
"""

from __future__ import annotations

from shared.governance_check import GovernanceCheck, GovernanceCheckResult, GovernanceContext

DEFAULT_MINIMUM_DURATION_SECONDS = 30 * 24 * 3600  # 30 jours


class MinimumContinuousModeDurationCheck(GovernanceCheck):
    check_name = "minimum_continuous_mode_duration"

    def __init__(self, minimum_seconds: int = DEFAULT_MINIMUM_DURATION_SECONDS) -> None:
        self._minimum_seconds = minimum_seconds

    def check(self, context: GovernanceContext) -> GovernanceCheckResult:
        if context.continuous_mode_duration_seconds >= self._minimum_seconds:
            return GovernanceCheckResult(self.check_name, passed=True)

        days_done = context.continuous_mode_duration_seconds / 86400
        days_required = self._minimum_seconds / 86400
        return GovernanceCheckResult(
            self.check_name,
            passed=False,
            reason=(
                f"Le mode courant ('{context.current_mode}') n'a été actif que "
                f"{days_done:.1f} jour(s) sans interruption, {days_required:.0f} requis."
            ),
        )
