from decimal import Decimal

from shared.risk_rule import RiskCheckResult, RiskContext, RiskRule

# Valeurs de départ prudentes (Phase 13, §5, §9) - à calibrer en Phase 14
MAX_RISK_FRACTION = Decimal("0.02")  # 2% du capital disponible par position, au maximum
KELLY_DIVISOR = Decimal("10")  # dénominateur de la fraction de Kelly plafonnée


class PositionSizingRule(RiskRule):
    """Calcule la quantité de la position via une fraction de Kelly plafonnée
    (Phase 1 : Kelly Criterion, Volatility Position Sizing ; Phase 13, §5).

    Une fraction de Kelly complète est notoirement agressive - plafonnée
    à MAX_RISK_FRACTION du capital disponible par position, par prudence
    délibérée en V1.
    """

    rule_name = "position_sizing"

    def check(self, context: RiskContext) -> RiskCheckResult:
        if context.current_price <= 0:
            return RiskCheckResult(
                rule_name=self.rule_name, passed=False, reason="Prix actuel invalide (<= 0)."
            )

        kelly_fraction = Decimal(str(context.risk_reward_ratio)) / KELLY_DIVISOR
        risk_fraction = min(kelly_fraction, MAX_RISK_FRACTION)

        if risk_fraction <= 0:
            return RiskCheckResult(
                rule_name=self.rule_name,
                passed=False,
                reason="Fraction de risque calculée nulle ou négative - pas de position dimensionnable.",
            )

        notional = context.available_capital * risk_fraction
        quantity = notional / context.current_price

        if quantity <= 0:
            return RiskCheckResult(
                rule_name=self.rule_name, passed=False, reason="Quantité calculée nulle ou négative."
            )

        context.suggested_quantity = quantity
        return RiskCheckResult(
            rule_name=self.rule_name,
            passed=True,
            reason=f"Quantité dimensionnée : {quantity} (fraction de risque {risk_fraction}).",
        )
