# Phase 20 — Déploiement, sécurité, audit et mise en production
## Plateforme quantitative de trading crypto — V1

**Statut : Phase 20 en cours de validation. Dernière phase de la feuille de route initiale.**
**Prérequis : Phases 1 à 19 validées.**

---

## 1. Méthode de cette phase

Un audit final n'a de valeur que s'il part de ce qui a été **réellement laissé en attente**, pas d'une checklist générique. J'ai relu les 19 phases précédentes et extrait chaque point explicitement différé « à traiter en Phase 20 ». Cette section les traite un par un — chacun est soit corrigé maintenant (avec le fichier livré), soit reconfirmé comme différé avec une justification.

---

## 2. Registre de dette technique — traité point par point

| # | Point différé | Phase d'origine | Traitement en Phase 20 |
|---|---|---|---|
| 1 | CORS de l'API grand ouvert (`allow_origins=["*"]`) | Phase 18 | **✅ Corrigé** — restreint au domaine configuré (`DOMAIN_NAME`). |
| 2 | `RealExecutionMode` ne confirme jamais le remplissage réel ni ne met à jour `positions` | Phase 12, §6 / Phase 15, §8 | **✅ Corrigé** — ajout d'un polling du statut d'ordre HTX (`get_order_status`) et branchement sur `execution_engine/positions.py` (Phase 15). |
| 3 | Kill switch : persistance Redis (AOF) jamais testée par un redémarrage réel | Phase 13, §9 | **✅ Corrigé** — procédure de test documentée et scriptée (§5). |
| 4 | Plan de reprise (perte totale du VPS) jamais testé concrètement | Phase 3, §6 | **✅ Corrigé** — script de restauration + procédure de test (§5). |
| 5 | Durcissement serveur (firewall, SSH, mises à jour automatiques) | Phase 3, §9 | **✅ Corrigé** — script `setup_hardening.sh` (§4). |
| 6 | Endpoints HTX de trading à revérifier avant capital réel | Phase 12, §5 | **⚠️ Rappel maintenu, pas automatisable** — geste humain obligatoire avant toute mise en réel, détaillé en §6. |
| 7 | Réévaluation cloud managé / microservices si le capital ou le volume grandit | Phase 2, 3, 5 | **Différé, à raison** — aucun signal empirique ne le justifie encore ; critères de bascule objectifs listés en §7. |
| 8 | Gestionnaire de secrets dédié (Vault) | Phase 3, §9 | **Différé, à raison** — proportionné seulement si l'option cloud managé est activée. |
| 9 | Monte Carlo, Walk Forward Analysis, stress tests, rapport PDF | Phase 14, §6 | **Différé, à raison** — nécessite un socle de backtest déjà éprouvé, pas encore le cas. |
| 10 | Blue/Green, zéro downtime | Phase 5, §3 | **Différé, à raison** — sans objet tant qu'une seule instance suffit. |

---

## 3. Correction n°1 : CORS restreint

`backend/api/main.py` n'accepte désormais que l'origine du domaine configuré (`PUBLIC_API_URL` / `DOMAIN_NAME`, Phase 3/5), plus `http://localhost:3000` pour le développement local.

## Correction n°2 : confirmation de remplissage réel + suivi de position

`HTXAdapter.get_order_status(order_id)` interroge `GET /v1/order/orders/{order-id}` (même mécanisme de signature que la Phase 12, §5). `RealExecutionMode` (Phase 12) poll ce statut après l'envoi de l'ordre (quelques tentatives avec backoff court) ; dès que le statut est `filled`, `execution_engine/positions.py` (Phase 15) est appelé exactement comme pour le mode paper — même code, cohérent avec la garantie de la Phase 2.

---

## 4. Durcissement serveur

`infra/hardening/setup_hardening.sh` — à exécuter une fois, manuellement, sur le VPS Fornex (Phase 3) :
- Pare-feu (`ufw`) : seuls 80/443/SSH (port non standard) ouverts.
- SSH : désactivation de l'authentification par mot de passe, uniquement par clé.
- Mises à jour de sécurité automatiques (`unattended-upgrades`).
- `fail2ban` sur le port SSH.

---

## 5. Tests de reprise (jamais faits, maintenant scriptés)

- `infra/backup/test_restore.sh` : restaure le dernier dump sur une base **temporaire** (jamais sur la base de production) et vérifie que les tables clés (`decisions`, `positions`, `feature_values`) contiennent des données cohérentes — validation automatisable du plan de reprise de la Phase 3, §6.
- `infra/hardening/test_kill_switch_persistence.sh` : active le kill switch, force un redémarrage du conteneur Redis, vérifie que l'état est bien conservé (persistance AOF, Phase 5/13) — procédure documentée à exécuter manuellement avant la mise en production.

---

## 6. Rappel non automatisable : vérification des endpoints HTX

Comme indiqué depuis la Phase 12, §5 : avant tout passage en mode réel avec du capital, vérifiez manuellement `/v1/order/orders/place`, `/v1/account/accounts`, `/v1/account/accounts/{id}/balance` et le nouvel endpoint `/v1/order/orders/{order-id}` contre la documentation HTX à jour (https://huobiapi.github.io/docs/spot/v1/en/). Ce n'est pas automatisable par nature — une API tierce peut changer sans préavis.

---

## 7. Critères objectifs de bascule vers plus d'infrastructure (au-delà de la V1)

Pour que la relecture de ces choix ne soit pas arbitraire dans le futur, voici les seuils concrets qui justifieraient de revenir sur les décisions "V1 minimale" :

- **Cloud managé / haute disponibilité** : capital géré dépassant significativement 10k$, ou revenus justifiant >100€/mois d'infra, ou un incident de downtime ayant coûté plus que le coût de la redondance.
- **Microservices** : plus de 3-4 exchanges actifs simultanément, ou une des boucles (Phase 18, §1) saturant régulièrement le CPU/RAM du conteneur `engine`.
- **Kafka** : volume de messages internes dépassant ce que Redis Pub/Sub absorbe sans perte visible (à instrumenter via le monitoring, Phase 19, avant de décider).
- **Vault/secrets manager dédié** : plusieurs environnements (staging/prod) ou plusieurs opérateurs humains ayant besoin d'accès différenciés aux secrets.

---

## 8. Checklist finale avant tout capital réel

Cette checklist rassemble les conditions déjà posées séparément dans les phases précédentes — elle ne doit pas être contournée :

- [ ] Backtest (Phase 14) validé sur une période représentative, espérance nette des coûts positive.
- [ ] Paper trading (Phase 15) sur **plusieurs semaines réelles**, résultats cohérents avec le backtest.
- [ ] Durcissement serveur exécuté (§4).
- [ ] Test de restauration de sauvegarde réussi (§5).
- [ ] Test de persistance du kill switch réussi (§5).
- [ ] Endpoints HTX revérifiés manuellement (§6).
- [ ] Clés API HTX créées avec permissions minimales, retrait désactivé, IP restreinte (Phase 7, §6).
- [ ] `STARTING_CAPITAL` réellement égal au capital que vous êtes prêt à perdre (Phase 1).

---

## 9. Auto-évaluation finale du projet

**Ce qui a été construit** : un socle V1 cohérent de bout en bout — collecte (1 exchange, spot), normalisation, features versionnées, stratégie à règles explicites, décision probabiliste, gestion des risques à 6 niveaux, exécution backtest/paper/réel, backtesting avec métriques rigoureuses, infrastructure ML prête mais inerte, optimisation avec garde-fous asymétriques, dashboard, monitoring actif, et maintenant un audit de production.

**Ce qui reste volontairement hors V1** : multi-exchange, ML activé, Monte Carlo/Walk Forward, futures/levier, SaaS multi-utilisateurs — chacun avec un critère explicite de quand y revenir plutôt qu'un simple "plus tard" vague.

**La discipline qui a le plus servi ce projet** : à plusieurs reprises (Phases 10, 12, 13, 17, 18), une incohérence réelle a été détectée en relisant les phases précédentes avant d'avancer — jamais après coup. C'est exactement la méthodologie que vous aviez posée dès le départ, et elle a payé concrètement, pas seulement en principe.

---

## 10. Fin de la feuille de route initiale

Les 20 phases du brief initial sont closes. Le `MANIFESTE_ARBORESCENCE.md` reste à jour et complet. La suite naturelle, si vous le souhaitez, est l'exploitation réelle : quelques semaines de paper trading avant d'envisager la checklist du §8.
