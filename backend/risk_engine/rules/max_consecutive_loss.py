"""Bloque toute NOUVELLE prise de risque après un nombre de pertes
consécutives jugé anormal (Phase 1 : Max Consecutive Loss ; Phase 13,
§6).

Correctif du 19/08/2026 (question légitime soulevée par l'opérateur en
observant une vraie pause en production) : cette règle bloquait
INDISTINCTEMENT toute décision, y compris celles qui auraient CLÔTURÉ
une position déjà ouverte - un vrai risque de blocage permanent pour le
spot, qui n'a aucun stop-loss automatique à l'exchange (contrairement
au futures, cf. `execution_engine.modes.real._attach_stop_loss`,
futures uniquement) : si une position spot reste ouverte au moment où
le seuil se déclenche ailleurs, la SEULE décision capable de la
clôturer aurait elle-même été refusée, la laissant bloquée
indéfiniment tant que la série de pertes ne se rompt pas d'elle-même -
ce qui ne pouvait jamais arriver puisque rien ne pouvait plus se
clôturer pour la rompre.

Second correctif, même soir, à la question suivante de l'opérateur
("après ces 3 pertes, de belles occasions se présentent - je suis
obligé de les rater ?") : la réponse initiale ("la pause se lève dès
qu'un trade clôture gagnant") était incomplète - sans position ouverte
à clôturer (le cas RÉEL sur ce déploiement au moment de la question,
cf. discussion), rien ne pouvait plus jamais clôturer, donc rien ne
pouvait plus jamais rompre la série : la pause n'était pas temporaire,
elle était DÉFINITIVE. Corrigé par une expiration dans le temps
(`PAUSE_EXPIRY` ci-dessous) - après un délai fixe sans nouvelle perte,
la pause se lève d'elle-même, qu'un trade ait clôturé gagnant ou non.
Troisième correctif, même soir : le seuil de 3 lui-même questionné par
l'opérateur, à raison - un ratio rendement/risque élevé (8-10x observés
en production ce soir) signe presque toujours un taux de réussite
INFÉRIEUR à 50% (petites pertes fréquentes compensées par de grands
gains rares) ; avec un taux de réussite plausible de 30-35% pour ce
profil, la probabilité de tomber sur 3 pertes d'affilée par pur hasard
- sans que rien ne soit réellement cassé - tourne autour de 27 à 42%.
Rendu réglable par variable d'environnement plutôt que de figer un
nouveau chiffre tout aussi arbitraire : l'opérateur peut désormais
recalibrer sans redéploiement, au fur et à mesure de l'observation
réelle du taux de réussite de chaque moteur.
"""

import os
from datetime import UTC, datetime, timedelta

from shared.risk_rule import RiskCheckResult, RiskContext, RiskRule

# Valeur de départ prudente (Phase 13, §9 ; rendue réglable le
# 19/08/2026 - cf. docstring du module pour le raisonnement statistique
# derrière ce changement) - à calibrer avec le taux de réussite RÉEL de
# chaque moteur une fois suffisamment de trades observés (Confidence
# Lifecycle, ADR-0015 : 30 trades minimum).
MAX_CONSECUTIVE_LOSSES = int(os.environ.get("MAX_CONSECUTIVE_LOSSES", "3"))

# Correctif du 19/08/2026 - délai maximal de la pause avant expiration
# automatique, même sans nouvelle clôture gagnante (cf. docstring du
# module). Valeur de départ prudente, même discipline que
# MAX_CONSECUTIVE_LOSSES ci-dessus - à calibrer avec de vraies données
# de marché (Phase 14), jamais pensée comme définitive.
PAUSE_EXPIRY = timedelta(hours=int(os.environ.get("MAX_CONSECUTIVE_LOSS_PAUSE_HOURS", "1")))


class MaxConsecutiveLossRule(RiskRule):
    """Sert de garde-fou contre un régime de marché où la stratégie ne
    fonctionne manifestement plus - une pause forcée sur les NOUVELLES
    prises de risque, jamais sur la capacité à s'en dégager (cf.
    docstring du module ci-dessus), et jamais indéfinie (PAUSE_EXPIRY)."""

    rule_name = "max_consecutive_loss"

    def check(self, context: RiskContext) -> RiskCheckResult:
        if context.open_position_quantity > 0:
            # Cette décision clôture (ou réduit) une position déjà
            # ouverte - jamais une nouvelle prise de risque. La bloquer
            # créerait exactement le risque de blocage permanent décrit
            # ci-dessus - toujours autorisée, quelle que soit la série
            # de pertes en cours.
            return RiskCheckResult(rule_name=self.rule_name, passed=True)

        if context.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
            if context.most_recent_loss_closed_at is not None:
                elapsed = datetime.now(tz=UTC) - context.most_recent_loss_closed_at
                if elapsed >= PAUSE_EXPIRY:
                    # La pause a expiré - le marché a eu le temps de
                    # changer de régime, jamais une pause pensée comme
                    # définitive (cf. docstring du module).
                    return RiskCheckResult(rule_name=self.rule_name, passed=True)

            return RiskCheckResult(
                rule_name=self.rule_name,
                passed=False,
                reason=(
                    f"{context.consecutive_losses} pertes consécutives détectées "
                    f"(seuil : {MAX_CONSECUTIVE_LOSSES}) - pause forcée sur les nouvelles positions "
                    f"pendant {PAUSE_EXPIRY} depuis la dernière perte "
                    f"(les clôtures de positions déjà ouvertes restent toujours autorisées)."
                ),
            )

        return RiskCheckResult(rule_name=self.rule_name, passed=True)
