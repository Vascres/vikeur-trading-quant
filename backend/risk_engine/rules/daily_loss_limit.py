from decimal import Decimal

from shared.risk_rule import RiskCheckResult, RiskContext, RiskRule

# Valeur de départ prudente (Phase 13, §9) - à calibrer en Phase 14
MAX_DAILY_LOSS_FRACTION = Decimal("0.05")  # 5% du capital disponible, perte journalière maximale


class DailyLossLimitRule(RiskRule):
    """Bloque toute nouvelle position si la perte réalisée du jour dépasse
    déjà le seuil autorisé (Phase 1 : Daily Loss Limit ; Phase 13, §6).
    """

    rule_name = "daily_loss_limit"

    def check(self, context: RiskContext) -> RiskCheckResult:
        max_allowed_loss = context.available_capital * MAX_DAILY_LOSS_FRACTION

        if context.daily_realized_pnl < 0 and abs(context.daily_realized_pnl) >= max_allowed_loss:
            return RiskCheckResult(
                rule_name=self.rule_name,
                passed=False,
                reason=(
                    f"Perte réalisée du jour ({context.daily_realized_pnl}) atteint ou dépasse "
                    f"la limite autorisée ({-max_allowed_loss})."
                ),
            )

        return RiskCheckResult(rule_name=self.rule_name, passed=True)
