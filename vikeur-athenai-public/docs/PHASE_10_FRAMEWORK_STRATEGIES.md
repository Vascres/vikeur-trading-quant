# Phase 10 — Framework des stratégies
## Plateforme quantitative de trading crypto — V1

**Statut : Phase 10 en cours de validation.**
**Prérequis : Phases 1 à 9 validées.**

---

## 1. Besoin métier de cette phase

Les features (Phase 9) mesurent l'état du marché, mais ne disent rien en elles-mêmes sur *quoi faire*. Il faut un mécanisme qui combine plusieurs features en une **proposition de position évaluée** (probabilité de succès, espérance mathématique, ratio rendement/risque) — c'est le rôle du contrat `Strategy` (Phase 2, §6).

## 2. Problème technique

Comment permettre à plusieurs stratégies de coexister, d'être comparées plus tard (Phase 17) et remplacées indépendamment, tout en gardant la même garantie de reproductibilité et de versionnement figé déjà appliquée aux features (Phase 9) ?

## 3. Ce que cette phase ne couvre PAS (délimitation explicite du périmètre)

- La **comparaison objective de plusieurs stratégies et l'allocation de capital** entre elles est le rôle de la **Phase 17 — Optimisation automatique**, pas de cette phase. Ici, on construit uniquement le cadre qui permettra à plusieurs stratégies actives de tourner en parallèle.
- Le **moteur de décision** qui orchestrera l'appel aux stratégies avec les features en temps réel est la **Phase 11**. Cette phase-ci ne livre que le contrat et une première implémentation de référence, testée en isolation.

---

## 4. Décision structurante : même mécanisme d'immutabilité que les features

**Constat** : la table `strategies` (Phase 6) a été créée avec une colonne `parameters JSONB` mais **sans colonne `logic_hash`** — un oubli à corriger avant que cette table soit utilisée pour de vrai. Conformément à la règle posée en Phase 6, §8 ("chaque évolution de schéma devra être une migration Alembic dédiée et atomique"), une migration `0002` est ajoutée dans cette phase pour réparer ce point, plutôt que de modifier rétroactivement la migration `0001` déjà validée.

Le mécanisme est ensuite strictement identique à celui des features (Phase 9, §3) : hash SHA-256 du code de la méthode `evaluate()`, comparé au hash enregistré pour `(name, version)` — refus de démarrage en cas de divergence.

---

## 5. Contrat `Strategy`

```
Strategy.evaluate(features: dict[str, float]) -> StrategyProposal | None
```

Une `StrategyProposal` contient : `symbol`, `suggested_side` (buy/sell), `success_probability` (0-1), `expected_value`, `risk_reward_ratio`, et `rationale` (un dictionnaire des valeurs de features utilisées — traçabilité directe vers `decisions.feature_snapshot_ids`, Phase 4 §7).

**Contrainte de conception** (identique aux features, Phase 9) : `evaluate()` est une fonction pure, aucun accès réseau/horloge/état externe — seulement les features passées en argument.

---

## 6. Stratégie de référence livrée : `MomentumImbalanceThreshold`

Une stratégie **volontairement simple et explicite** (règles, pas de ML — cohérent avec la Phase 1/2), qui combine les 5 features de la Phase 9 :

- **Signal directionnel** : `momentum` et `order_flow_imbalance` doivent pointer dans le même sens (accord entre la tendance de prix et la pression du carnet) — sinon pas de signal.
- **Probabilité de succès** : une fonction croissante de l'accord entre les deux signaux et de leur magnitude, plafonnée à des valeurs raisonnables (jamais 0% ni 100% - une règle simple ne justifie jamais une certitude absolue).
- **Espérance mathématique** : magnitude attendue du mouvement (proxy : `momentum`) diminuée du coût estimé (`spread_bps` converti en proportion).
- **Ratio rendement/risque** : magnitude attendue rapportée à la `realized_volatility` (le risque).
- Si le spread est anormalement élevé ou la volatilité nulle (données insuffisantes), la stratégie retourne `None` — pas de proposition plutôt qu'une proposition non fiable.

Cette stratégie est un **point de départ calibrable**, pas une prétention de edge réel — sa seule performance sera jugée en Phase 14 (backtesting), jamais supposée a priori.

---

## 7. Fichiers produits dans cette phase

- `backend/migrations/versions/0002_add_strategy_logic_hash.py` — ajout de la colonne manquante.
- `backend/shared/strategy.py` — contrat `Strategy` et `StrategyProposal`.
- `backend/strategies/momentum_imbalance_threshold.py` — stratégie de référence.
- `backend/strategies/registry.py` — enregistrement + vérification d'immutabilité (miroir de `feature_engine/registry.py`).
- `backend/tests/test_strategies.py` — tests de la logique de scoring + de l'immutabilité.

---

## 8. Interactions avec le reste du système

- Le module `strategies/` ne dépend que de `shared/strategy.py` — jamais de `feature_engine`, `decision_engine`, ou `execution_engine` directement (il reçoit un dictionnaire de features déjà calculées, fourni par l'appelant — le Moteur de décision, Phase 11).
- Le Moteur de décision (Phase 11) sera responsable d'assembler le dictionnaire `features` à partir de `feature_values` (Phase 6) avant d'appeler `evaluate()`.

---

## 9. Auto-évaluation

**Faiblesses identifiées :**
- La colonne `logic_hash` manquante en Phase 6 confirme le risque déjà identifié dans l'auto-évaluation de cette même phase (schéma initial trop large, oublis possibles) — corrigé ici via une migration dédiée, comme prévu.
- La stratégie de référence est simpliste par construction ; elle ne doit surtout pas être interprétée comme "prête pour le réel" avant la Phase 14/15.

**Cohérence avec les phases précédentes :** ✅ même discipline de versionnement que les features (Phase 9), respecte le contrat Phase 2 §6, prépare la Phase 11 sans l'anticiper.

---

## 10. Prochaine étape

Phase 11 — Moteur de décision probabiliste : orchestration réelle (assemblage des features depuis la base, appel des stratégies actives, seuils de décision, écriture dans `decisions`).
