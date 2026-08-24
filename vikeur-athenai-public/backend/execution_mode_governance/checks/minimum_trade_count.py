"""Prérequis : nombre minimal de transactions dans le mode courant (ADR-0004/0008)."""

from __future__ import annotations

from shared.governance_check import GovernanceCheck, GovernanceCheckResult, GovernanceContext

DEFAULT_MINIMUM_TRADE_COUNT = 50


class MinimumTradeCountCheck(GovernanceCheck):
    check_name = "minimum_trade_count"

    def __init__(self, minimum_trade_count: int = DEFAULT_MINIMUM_TRADE_COUNT) -> None:
        self._minimum_trade_count = minimum_trade_count

    def check(self, context: GovernanceContext) -> GovernanceCheckResult:
        if context.trade_count_since_mode_start >= self._minimum_trade_count:
            return GovernanceCheckResult(self.check_name, passed=True)

        return GovernanceCheckResult(
            self.check_name,
            passed=False,
            reason=(
                f"{context.trade_count_since_mode_start} transaction(s) fermée(s) depuis le début "
                f"du mode '{context.current_mode}', {self._minimum_trade_count} requises."
            ),
        )
