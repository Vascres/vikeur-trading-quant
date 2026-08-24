from decimal import Decimal

from shared.order_book import walk_order_book
from shared.risk_rule import RiskCheckResult, RiskContext, RiskRule
from shared.strategy import Side

# Valeur de départ prudente (Phase 13, §9) - inchangée par ADR-0016, ne
# concerne que le slippage (calculé en direct sur le carnet d'ordres
# réel, jamais une constante). Le seuil de frais (`ASSUMED_ROUND_TRIP_FEE_BPS`,
# 20 bps, jamais mesuré) a été retiré par ADR-0016 : `context.expected_value`
# est désormais net des frais réels mesurés (cost_model, `meta_engine/
# cost_estimation.py`) - ce filtre vérifie seulement que la marge nette
# qui reste après ces frais reste positive, sans réappliquer une
# deuxième estimation de frais non synchronisée avec la première (bug
# identifié lors du diagnostic du 1er août 2026 : les deux constantes,
# ASSUMED_FEE_BPS et ASSUMED_ROUND_TRIP_FEE_BPS, n'étaient synchronisées
# que par un commentaire, jamais par un test).
MAX_SLIPPAGE_BPS = Decimal(20)


class LiquiditySlippageFeesRule(RiskRule):
    """Porte les 3 critères de la Phase 1 différés depuis la Phase 11, §3 :
    liquidité suffisante, slippage sous le seuil, frais couverts par
    l'espérance mathématique (ADR-0016 : frais désormais mesurés en
    amont, ce filtre vérifie que la marge nette résultante est positive).
    """

    rule_name = "liquidity_slippage_fees"

    def check(self, context: RiskContext) -> RiskCheckResult:
        if context.suggested_quantity is None:
            return RiskCheckResult(
                rule_name=self.rule_name, passed=False, reason="Aucune quantité dimensionnée à vérifier."
            )

        book_side = context.order_book_asks if context.suggested_side == Side.BUY else context.order_book_bids
        if not book_side:
            return RiskCheckResult(
                rule_name=self.rule_name, passed=False, reason="Carnet d'ordres vide ou indisponible."
            )

        estimated_avg_price, filled_quantity = self._walk_order_book(book_side, context.suggested_quantity)

        if filled_quantity < context.suggested_quantity:
            return RiskCheckResult(
                rule_name=self.rule_name,
                passed=False,
                reason=(
                    f"Liquidité insuffisante : seulement {filled_quantity} disponible sur "
                    f"{context.suggested_quantity} demandé aux niveaux fournis du carnet."
                ),
            )

        best_price = book_side[0][0]
        slippage_bps = abs(estimated_avg_price - best_price) / best_price * Decimal(10_000)
        if slippage_bps > MAX_SLIPPAGE_BPS:
            return RiskCheckResult(
                rule_name=self.rule_name,
                passed=False,
                reason=f"Slippage estimé ({slippage_bps:.2f} bps) dépasse le seuil ({MAX_SLIPPAGE_BPS} bps).",
            )

        expected_value_bps = Decimal(str(context.expected_value)) * Decimal(10_000)
        if expected_value_bps <= 0:
            return RiskCheckResult(
                rule_name=self.rule_name,
                passed=False,
                reason=(
                    f"Espérance nette de frais mesurés ({expected_value_bps:.2f} bps) non positive "
                    "(ADR-0016 - frais déjà déduits en amont, cf. meta_engine/cost_estimation.py)."
                ),
            )

        return RiskCheckResult(rule_name=self.rule_name, passed=True)

    @staticmethod
    def _walk_order_book(
        levels: list[tuple[Decimal, Decimal]], target_quantity: Decimal
    ) -> tuple[Decimal, Decimal]:
        """Simule le remplissage niveau par niveau, retourne (prix moyen pondéré, quantité totale remplie).

        Délègue à `shared/order_book.py` (ADR-0021) - extrait pour être
        réutilisable par le simulateur d'exécution de paires sans
        dupliquer cette logique déjà testée. Interface publique inchangée."""
        return walk_order_book(levels, target_quantity)
