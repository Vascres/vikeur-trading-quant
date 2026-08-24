"""Plafond d'exposition notionnelle futures (ADR-0018, révisé par
décision CTO le 16/08/2026 - Étapes 7-8).

Historique : ADR-0018 imposait `notionnel <= capital disponible`, un
proxy direct de "jamais de levier" (1x implicite). Cette règle vérifie
désormais que la MARGE requise (notionnel / `MAX_LEVERAGE`) reste dans
le capital disponible, plutôt que le notionnel brut - c'est le
changement concret qui traduit la décision CTO du 16/08/2026 en code :
un compte de 350$ peut désormais dimensionner une position dont le
notionnel dépasse son capital, tant que la marge réellement engagée
(divisée par le levier système, 2x) reste couverte.

Ne s'applique qu'aux décisions `market_type='futures_perpetual'` - le
spot reste gouverné par `SpotNoShortingRule`/`MaxExposureRule` déjà
existantes, inchangées.

Portée volontairement limitée à CETTE position (pas l'agrégat des
positions futures déjà ouvertes) - même portée que la version d'origine
de cette règle ; l'exposition notionnelle AGRÉGÉE (toutes positions,
spot et futures confondues) reste bornée séparément par
`MaxExposureRule` (30% du capital), qui n'a pas besoin de connaître le
levier pour rester une garde-fou valide.

Limitation assumée (inchangée depuis ADR-0018 §4) : utilise
`context.available_capital` comme proxy du capital réellement engagé -
une vraie séparation du solde de marge futures (distinct du solde spot
sur un exchange réel) reste différée à un futur chantier d'extension de
`PortfolioProvider`.
"""

from shared.futures_margin import MAX_LEVERAGE, compute_required_margin
from shared.risk_rule import RiskCheckResult, RiskContext, RiskRule


class FuturesNotionalExposureCapRule(RiskRule):
    rule_name = "futures_notional_exposure_cap"

    def check(self, context: RiskContext) -> RiskCheckResult:
        if context.market_type != "futures_perpetual":
            return RiskCheckResult(rule_name=self.rule_name, passed=True)

        if context.suggested_quantity is None:
            return RiskCheckResult(
                rule_name=self.rule_name, passed=False, reason="Aucune quantité dimensionnée à vérifier."
            )

        proposed_notional = context.suggested_quantity * context.current_price
        required_margin = compute_required_margin(proposed_notional, MAX_LEVERAGE)

        if required_margin > context.available_capital:
            return RiskCheckResult(
                rule_name=self.rule_name,
                passed=False,
                reason=(
                    f"Marge requise ({required_margin}) pour un notionnel de {proposed_notional} "
                    f"à {MAX_LEVERAGE}x dépasserait le capital disponible ({context.available_capital})."
                ),
            )

        return RiskCheckResult(rule_name=self.rule_name, passed=True)
