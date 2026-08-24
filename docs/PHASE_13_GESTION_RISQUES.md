# Phase 13 — Gestion des risques
## Plateforme quantitative de trading crypto — V1

**Statut : Phase 13 en cours de validation.**
**Prérequis : Phases 1 à 12 validées.**

---

## 1. Besoin métier de cette phase

C'est le module le plus critique du système : celui qui a le **dernier mot** avant qu'un ordre parte (Phase 2, §4.6). Il porte les trois critères de la Phase 1 laissés en attente depuis la Phase 11 (liquidité, frais, slippage), le dimensionnement des positions, et les mécanismes de protection du capital (kill switch, limite de perte journalière, pertes consécutives).

## 2. Problème technique

Trois problèmes à résoudre :
1. Comment garder une trace de **chaque règle évaluée individuellement** (Phase 4, §7 : "risk_checks.decision_id → toutes les règles évaluées + verdicts") tout en respectant la contrainte du schéma (Phase 6) où `orders.risk_check_id` référence **une seule ligne** `risk_checks` ?
2. Comment dimensionner une position (aucune notion de quantité n'existe encore dans `decisions`, Phase 6 — c'est une omission volontaire : le dimensionnement est la responsabilité du Moteur de risque, pas du Moteur de décision) ?
3. Où stocker un kill switch qui doit être lisible/modifiable en quasi temps réel ?

---

## 3. Décision de conception : ligne de verdict final

**Choix retenu** : pour chaque décision évaluée, le Moteur de risque insère une ligne `risk_checks` **par règle** (`rule_name`, `passed`, `reason`), puis une ligne supplémentaire de synthèse (`rule_name = 'FINAL_VERDICT'`, `passed` = ET logique de toutes les règles). C'est **l'id de cette ligne de synthèse** que référence `orders.risk_check_id`. La traçabilité complète (Phase 4, §7) reste intacte : en remontant par `decision_id`, on retrouve toutes les règles individuelles ET le verdict final utilisé pour l'exécution.

## 4. Décision de conception : le kill switch vit dans Redis

Le kill switch doit être lisible/modifiable en quasi temps réel, y compris manuellement via l'API (action de contrôle, Phase 2 §4.9). **Redis** (déjà en place, Phase 3, avec persistance AOF activée dans `docker-compose.yml`, Phase 5) est le bon outil : c'est un indicateur opérationnel volatile par nature, pas une donnée historique à analyser — la distinction déjà posée en Phase 4, §6 entre donnée d'explicabilité (toujours en base) et état opérationnel courant.

## 4bis. Correction d'un oubli du même type qu'en Phase 10

En assemblant le contexte de risque, il est apparu que la table `decisions` (Phase 6) ne stockait pas le **sens** de la position (achat/vente) — sans cette information, le Moteur de risque n'aurait pas pu savoir dans quelle direction exécuter. Plutôt que de contourner par une valeur par défaut, une migration `0003_add_decision_side` ajoute la colonne manquante, et le Moteur de décision (Phase 11) est mis à jour pour l'enregistrer à chaque décision. Même discipline que la Phase 10 : un oubli de schéma se corrige par une migration dédiée, jamais par un raccourci silencieux dans le code applicatif.

## 5. Dimensionnement des positions (Phase 1 : Kelly Criterion, Volatility Position Sizing)

Formule retenue, volontairement simple (règle explicite, pas de ML — cohérent Phase 1/2) :

```
capital_disponible = capital_initial + somme(positions.realized_pnl)
fraction_kelly_plafonnée = min(risk_reward_ratio / 10, MAX_RISK_FRACTION)  # MAX_RISK_FRACTION = 0.02 (2% du capital par position, valeur de départ)
notionnel_position = capital_disponible * fraction_kelly_plafonnée
quantité = notionnel_position / prix_actuel
```

Une fraction de Kelly complète est notoirement agressive et instable en pratique ; le plafond à 2% du capital par position est une prudence délibérée pour la V1 (capital <10k$, Phase 1) — à recalibrer en Phase 14 avec des données réelles de backtest, jamais avant.

---

## 6. Règles actives (Chain of Responsibility, Phase 2 §4.6)

| Règle | Vérifie | Source |
|---|---|---|
| `KillSwitchRule` | Le kill switch n'est pas actif (Redis) | Phase 1 (protection globale) |
| `PositionSizingRule` | Calcule la quantité (§5) et vérifie qu'elle est positive et cohérente | Phase 1 (Kelly/volatilité) |
| `MaxExposureRule` | Exposition totale du portefeuille après cette position ≤ seuil configuré | Phase 1 (Portfolio Exposure) |
| `DailyLossLimitRule` | Perte réalisée du jour ≥ -seuil configuré | Phase 1 (Daily Loss Limit) |
| `MaxConsecutiveLossRule` | Nombre de pertes consécutives < seuil configuré | Phase 1 (Max Consecutive Loss) |
| `LiquiditySlippageFeesRule` | Profondeur du carnet suffisante pour la quantité visée sans dépasser le slippage max ; frais couverts par l'espérance | Phase 1 (les 3 critères différés de la Phase 11) |

Toutes les règles sont évaluées **systématiquement**, même si une règle précédente a déjà échoué — pour garder un audit complet (§3), pas seulement la première cause de rejet.

---

## 7. Fichiers produits dans cette phase

- `backend/migrations/versions/0003_add_decision_side.py` — correction du schéma (§4bis).
- `backend/decision_engine/main.py` **(mis à jour)** — enregistre désormais `suggested_side`.
- `backend/shared/risk_rule.py` — contrat `RiskRule`, `RiskContext`, `RiskCheckResult`.
- `backend/risk_engine/rules/*.py` — les 6 règles du §6.
- `backend/risk_engine/main.py` — orchestration : assemble le contexte, exécute les règles, écrit `risk_checks`, retourne les résultats (jamais d'appel à l'exécution).
- `backend/execution_engine/main.py` — orchestrateur final (nouveau, comble aussi le manque d'entrypoint de la Phase 12) : reconstruction d'état au démarrage, boucle d'appel au risque puis à l'exécution.
- `backend/tests/test_risk_engine.py` — tests de chaque règle en isolation.

---

## 8. Interactions avec le reste du système — la boucle est maintenant complète

```
decisions (verdict='signal', Phase 11)
   → risk_engine.evaluate_pending_decisions() assemble le RiskContext,
     exécute les 6 règles, écrit risk_checks (Phase 6), retourne un
     RiskOutcome par décision (jamais d'appel à execution_engine ici)
   → execution_engine/main.py (l'orchestrateur, couche la plus haute)
     lit ces RiskOutcome et appelle execution_mode.execute(...) si validé
   → orders / positions (Phase 6)
```

**Correction architecturale notable** : une première version faisait appeler `execution_engine` directement depuis `risk_engine` pour déclencher l'exécution après validation. C'est une violation de l'ordre des couches défini en Phase 2/5 (`execution_engine` est la couche la plus haute — elle peut importer `risk_engine`, jamais l'inverse), détectée avant livraison. Le module `risk_engine` a été restructuré pour rester un pur évaluateur : il écrit `risk_checks` et retourne un `RiskOutcome` par décision, sans jamais appeler l'exécution lui-même. C'est `execution_engine/main.py` (nouveau fichier, l'orchestrateur final) qui lit ces résultats et déclenche l'exécution — cohérent avec le principe déjà énoncé en Phase 2 : l'exécution dépend du risque, jamais l'inverse.

---

## 9. Auto-évaluation

**Faiblesses identifiées et corrigées pendant cette phase :**
- Une violation de l'ordre des couches (`risk_engine` appelant `execution_engine`) a été détectée et corrigée avant livraison (§8) — l'orchestration finale vit maintenant dans `execution_engine/main.py`, qui comble aussi un manque : la Phase 12 n'avait pas produit de point d'entrée exécutable pour le moteur d'exécution, seulement ses composants.
- Le calcul de `capital_disponible` suppose un `capital_initial` configuré manuellement (variable d'environnement) — cohérent avec un système à opérateur unique (Phase 1), mais deviendrait insuffisant pour un usage multi-utilisateurs (hors périmètre V1).
- Les seuils (`MAX_RISK_FRACTION`, limite de perte journalière, pertes consécutives) sont des valeurs de départ prudentes mais arbitraires — à calibrer en Phase 14.

**Risques de conception :**
- Le kill switch dans Redis dépend de la persistance AOF (Phase 5) pour survivre à un redémarrage — vérifié en configuration, mais à tester concrètement (redémarrage forcé + vérification de l'état) avant la mise en production (Phase 20).

**Cohérence avec les phases précédentes :** ✅ ferme exactement la boucle prévue depuis la Phase 2 ; respecte la délimitation de responsabilités actée en Phase 11, §3.

---

## 10. Prochaine étape

Phase 14 — Backtesting : rejouer l'historique à travers ce pipeline complet (Décision → Risque → Exécution en mode backtest) et mesurer objectivement la performance (Sharpe, Sortino, Max Drawdown...).
