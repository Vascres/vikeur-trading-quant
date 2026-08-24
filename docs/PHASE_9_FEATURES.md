# Phase 9 — Construction des features
## Plateforme quantitative de trading crypto — V1

**Statut : Phase 9 en cours de validation.**
**Prérequis : Phases 1 à 8 validées.**

---

## 1. Besoin métier de cette phase

Le Moteur de décision (Phase 11) ne peut pas raisonner sur des prix bruts — il a besoin de variables synthétiques (features) mesurant l'état du marché. Cette phase construit le `feature_engine` (Phase 2, §4.4) et un **premier socle restreint mais réellement exploitable** de features, plutôt que la longue liste du brief initial d'un coup (cohérent avec la Phase 1 : sophistication progressive, pas immédiate).

## 2. Problème technique

Comment calculer des features de façon **reproductible** (même feature, même donnée en entrée → toujours le même résultat) et **versionnée de façon réellement infalsifiable** (pas seulement "documentée comme figée" mais techniquement impossible à modifier silencieusement) ?

---

## 3. Décision structurante : versionnement par hash de code

**Problème identifié dans l'auto-évaluation de la Phase 4** : le versionnement figé des features reposait sur la discipline humaine ("ne jamais modifier une version existante"). Une discipline seule n'est pas une garantie technique.

**Solution retenue** : chaque feature est une fonction Python pure. Au démarrage du `feature_engine`, un **hash SHA-256 du code source** de chaque fonction de calcul est comparé au hash enregistré dans `feature_definitions` (Phase 6) pour cette version :
- Si la version n'existe pas encore → elle est créée avec le hash actuel.
- Si la version existe et le hash correspond → rien à faire.
- **Si la version existe et le hash diffère → le service refuse de démarrer**, avec un message explicite demandant de créer une nouvelle version plutôt que de modifier l'existante.

Cela transforme une règle documentée (Phase 4) en une **contrainte technique appliquée automatiquement**, conformément à la mitigation prévue dans l'auto-évaluation de la Phase 4.

---

## 4. Features retenues pour la V1 (socle restreint, extensible)

| Feature | Ce qu'elle mesure | Source de données |
|---|---|---|
| `spread_bps` | Écart bid/ask relatif, en points de base | `order_book_snapshots` (Phase 6) |
| `order_flow_imbalance` | Déséquilibre entre volume à l'achat et à la vente sur les N premiers niveaux du carnet | `order_book_snapshots` |
| `realized_volatility` | Volatilité réalisée (écart-type des rendements log) sur une fenêtre glissante | `ohlcv_candles_1m` (Phase 6) |
| `vwap` | Prix moyen pondéré par le volume sur la fenêtre | `ohlcv_candles_1m` |
| `momentum` | Variation relative du prix de clôture sur N périodes | `ohlcv_candles_1m` |

Ce socle correspond à une sélection volontairement réduite (prix, carnet, volatilité, tendance) — suffisante pour un premier Moteur de décision à règles explicites (Phase 11). Les variables plus avancées du brief initial (sentiment, on-chain, macro, footprint...) restent dans la vision long terme et seront ajoutées **une par une**, chacune suivant exactement ce même mécanisme de versionnement, une fois ce socle validé en backtest (Phase 14).

---

## 5. Fichiers produits dans cette phase

- `backend/shared/feature.py` — contrat `Feature` (Phase 2, §6).
- `backend/feature_engine/features/*.py` — implémentation des 5 features du §4.
- `backend/feature_engine/registry.py` — enregistrement + vérification d'immutabilité par hash.
- `backend/feature_engine/main.py` — boucle de calcul périodique, écriture dans `feature_values`.
- `backend/tests/test_features.py` — tests de chaque calcul + test de la vérification d'immutabilité.

---

## 6. Interactions avec le reste du système

- Lit `ohlcv_candles_1m` et `order_book_snapshots` (Phase 6), écrits par le Normalizer (Phase 8).
- Écrit dans `feature_values`, en référençant toujours un `feature_definition_id` validé par le registre (§3).
- Ne dépend jamais du Moteur de décision (Phase 2, contrat import-linter, couche `feature_engine` sous `decision_engine`).

---

## 7. Auto-évaluation

**Faiblesses identifiées :**
- Le hash de code source détecte tout changement de logique, mais aussi des changements purement cosmétiques (renommage de variable locale, reformatage) qui ne changent pas le résultat. *Conséquence acceptée* : cela peut forcer une nouvelle version un peu "par excès de prudence", mais jamais l'inverse (aucun changement silencieux ne peut passer) — le compromis est jugé sain pour un système gérant du capital réel.
- Les fenêtres de calcul (ex. 20 périodes pour la volatilité) sont des valeurs de départ raisonnables mais non encore calibrées empiriquement — ce calibrage viendra avec le backtesting (Phase 14).

**Cohérence avec les phases précédentes :** ✅ opérationnalise directement la mitigation prévue en Phase 4 ; respecte les frontières de la Phase 2.

---

## 8. Prochaine étape

Phase 10 — Framework des stratégies : contrat `Strategy` (Phase 2, §6) permettant de combiner plusieurs features en un score, avec le même mécanisme de versionnement figé.
