from decimal import Decimal

from shared.risk_rule import RiskCheckResult, RiskContext, RiskRule

# Valeur de départ prudente (Phase 13, §9) - à calibrer en Phase 14
MAX_EXPOSURE_FRACTION = Decimal("0.30")  # 30% du capital disponible, exposition totale maximale


class MaxExposureRule(RiskRule):
    """Vérifie que l'exposition totale du portefeuille, après cette
    nouvelle position, ne dépasse pas un seuil du capital disponible
    (Phase 1 : Portfolio Exposure ; Phase 13, §6).
    """

    rule_name = "max_exposure"

    def check(self, context: RiskContext) -> RiskCheckResult:
        if context.suggested_quantity is None:
            return RiskCheckResult(
                rule_name=self.rule_name,
                passed=False,
                reason="Aucune quantité dimensionnée (position_sizing a échoué ou n'a pas encore tourné).",
            )

        new_position_notional = context.suggested_quantity * context.current_price
        projected_exposure = context.current_exposure_notional + new_position_notional
        max_allowed = context.available_capital * MAX_EXPOSURE_FRACTION

        if projected_exposure > max_allowed:
            return RiskCheckResult(
                rule_name=self.rule_name,
                passed=False,
                reason=(
                    f"Exposition projetée {projected_exposure} dépasse le maximum autorisé "
                    f"{max_allowed} ({MAX_EXPOSURE_FRACTION * 100}% du capital)."
                ),
            )

        return RiskCheckResult(rule_name=self.rule_name, passed=True)
