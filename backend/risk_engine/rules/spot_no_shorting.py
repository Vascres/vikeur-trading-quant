from shared.risk_rule import RiskCheckResult, RiskContext, RiskRule
from shared.strategy import Side


class SpotNoShortingRule(RiskRule):
    """Bloque toute vente sans position ouverte suffisante (Phase 15, §4).

    Le spot ne permet pas la vente à découvert - contrairement aux
    futures/perpétuels (ADR-0018), une vente ne peut que clôturer une
    position déjà détenue. Ne s'applique qu'aux décisions
    `market_type='spot'` (défaut) - une vente en `futures_perpetual` est
    gouvernée par `FuturesNotionalExposureCapRule` à la place, jamais par
    cette règle (ADR-0018 §3.2 : une règle, une responsabilité claire).
    """

    rule_name = "spot_no_shorting"

    def check(self, context: RiskContext) -> RiskCheckResult:
        if context.market_type != "spot":
            return RiskCheckResult(rule_name=self.rule_name, passed=True)

        if context.suggested_side != Side.SELL:
            return RiskCheckResult(rule_name=self.rule_name, passed=True)

        if context.open_position_quantity <= 0:
            return RiskCheckResult(
                rule_name=self.rule_name,
                passed=False,
                reason="Vente refusée : aucune position ouverte à clôturer (spot, pas de vente à découvert).",
            )

        return RiskCheckResult(rule_name=self.rule_name, passed=True)
