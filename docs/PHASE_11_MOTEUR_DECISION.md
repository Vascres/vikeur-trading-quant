# Phase 11 — Moteur de décision probabiliste
## Plateforme quantitative de trading crypto — V1

**Statut : Phase 11 en cours de validation.**
**Prérequis : Phases 1 à 10 validées.**

---

## 1. Besoin métier de cette phase

C'est ici que le système prend forme réellement : assembler les features fraîches, appeler les stratégies actives, appliquer les critères de la Phase 1 (§3 : espérance positive, ratio rendement/risque acceptable, niveau de confiance suffisant), et **journaliser chaque évaluation** — que la conclusion soit un signal ou non.

## 2. Problème technique

Trois problèmes concrets à résoudre :
1. Comment assembler, pour un instant donné, un dictionnaire de features **fraîches** (pas des valeurs périmées suite à une déconnexion ou un retard de calcul) ?
2. Où placer exactement la frontière entre ce que la Phase 1 demande ("liquidité suffisante", "frais couverts", "slippage sous seuil") et ce que le Moteur de risque (Phase 13) doit vérifier ?
3. Comment garder une trace exploitable même quand une stratégie ne produit aucune proposition ?

---

## 3. Délimitation des responsabilités (point important)

La Phase 1 énonce six critères avant toute position. Ils se répartissent entre deux modules distincts (Phase 2, §4.5-4.6), et cette phase ne traite que les trois premiers :

| Critère (Phase 1, §3) | Module responsable | Phase |
|---|---|---|
| Espérance mathématique positive | **Moteur de décision** | Phase 11 (ici) |
| Ratio rendement/risque acceptable | **Moteur de décision** | Phase 11 (ici) |
| Niveau de confiance suffisant | **Moteur de décision** | Phase 11 (ici) |
| Liquidité suffisante | Moteur de risque | Phase 13 |
| Frais couverts | Moteur de risque | Phase 13 |
| Slippage sous le seuil défini | Moteur de risque | Phase 13 |

Raison de ce découpage (déjà actée en Phase 2, §4.5-4.6) : la liquidité/le slippage dépendent de l'état du carnet **au moment précis de l'exécution** et de la taille de position envisagée (donc du portefeuille) — des informations que le Moteur de décision ne doit délibérément pas connaître (il reste pur, indépendant de l'exécution). Le Moteur de risque, lui, a le dernier mot et ces informations.

---

## 4. Décision : gestion des cas "pas de proposition"

Quand une stratégie retourne `None` (Phase 10 — signal insuffisant, spread trop élevé, etc.), il n'y a pas de nombres à enregistrer dans `decisions` (dont les colonnes numériques sont `NOT NULL`, Phase 6). **Décision retenue** : ce cas est journalisé dans `events_journal` (Phase 4, §5.5) avec les valeurs de features en `payload` — pas dans `decisions`. Le pipeline reste donc explicable dans les deux cas, mais via deux mécanismes différents :
- **Stratégie déclenchée avec des chiffres** (proposition produite) → toujours une ligne dans `decisions`, que le verdict final soit `signal` ou `no_signal` après application des seuils du Moteur de décision (§5).
- **Stratégie non déclenchée** (aucune proposition, `None`) → un événement `decision_engine.no_proposal` dans le Journal, avec les features brutes en contexte.

C'est un compromis assumé : pas de migration de schéma supplémentaire, et une explicabilité complète bien que répartie sur deux tables.

---

## 5. Seuils de décision (Phase 1, §3)

```python
DECISION_THRESHOLDS = {
    "min_success_probability": 0.55,
    "min_expected_value": 0.0,       # doit être strictement positif
    "min_risk_reward_ratio": 1.5,
}
```
Une proposition passe au verdict `signal` uniquement si les trois seuils sont respectés simultanément. Ce sont des valeurs de départ raisonnables, **non calibrées empiriquement** — le calibrage réel viendra du backtesting (Phase 14).

## 6. Fraîcheur des données

Avant tout calcul, le Moteur de décision vérifie que la feature la plus récente disponible pour chaque définition n'est pas plus vieille que `FEATURE_FRESHNESS_SECONDS` (120s — le double de l'intervalle de calcul du Feature Builder, Phase 9, pour absorber un cycle de retard sans être trop permissif). Au-delà, l'évaluation est annulée pour ce symbole et un événement `decision_engine.stale_data` est journalisé — jamais de décision prise sur une donnée qu'on sait périmée (exigence implicite de la Phase 1 : la fiabilité prime sur la réactivité).

---

## 7. Fichiers produits dans cette phase

- `backend/decision_engine/thresholds.py` — seuils + fonctions pures de décision (testables sans base de données).
- `backend/decision_engine/main.py` — boucle d'orchestration (assemblage features, appel stratégies, écriture `decisions`).
- `backend/tests/test_decision_engine.py` — tests des fonctions pures de seuillage et de fraîcheur.

---

## 8. Interactions avec le reste du système

- Importe `feature_engine.registry` (liste des features actives) et `strategies.registry` (liste des stratégies actives) — autorisé par les couches définies en Phase 2/10 (`decision_engine` peut importer `feature_engine`, jamais l'inverse).
- Écrit dans `decisions` (Phase 6), en référençant `strategy_id` et les `feature_snapshot_ids` réels (ids des lignes `feature_values` utilisées) — traçabilité complète (Phase 4, §7).
- N'importe **jamais** `execution_engine`, `risk_engine`, ou `data_collector` (contrats import-linter, Phase 2/5).

---

## 9. Auto-évaluation

**Faiblesses identifiées :**
- Les seuils (§5) et la fenêtre de fraîcheur (§6) sont des valeurs de départ non calibrées — assumé et explicitement différé au backtesting (Phase 14).
- Le partage de l'explicabilité entre `decisions` et `events_journal` (§4) demande de consulter les deux tables pour une vue complète — un choix pragmatique plutôt qu'une modification de schéma supplémentaire à ce stade.

**Cohérence avec les phases précédentes :** ✅ respecte strictement la délimitation Décision/Risque actée en Phase 2 ; s'appuie sur les registres de features (Phase 9) et de stratégies (Phase 10) sans dupliquer leur logique.

---

## 10. Prochaine étape

Phase 12 — Moteur d'exécution des ordres : implémentation des 3 modes (backtest/paper/réel) derrière l'interface commune définie en Phase 2, §4.7, et activation réelle des méthodes de trading de l'`ExchangeAdapter` HTX (Phase 7).
