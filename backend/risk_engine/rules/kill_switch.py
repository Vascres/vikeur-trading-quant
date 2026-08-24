from shared.risk_rule import RiskCheckResult, RiskContext, RiskRule


class KillSwitchRule(RiskRule):
    """Vérifie que le kill switch global n'est pas actif (Phase 13, §4).

    L'état du kill switch est lu depuis Redis par l'appelant et injecté
    dans le contexte - cette règle reste une fonction pure du contexte.
    """

    rule_name = "kill_switch"

    def check(self, context: RiskContext) -> RiskCheckResult:
        if context.kill_switch_active:
            return RiskCheckResult(
                rule_name=self.rule_name,
                passed=False,
                reason="Kill switch actif - toute nouvelle position est bloquée.",
            )
        return RiskCheckResult(rule_name=self.rule_name, passed=True)
