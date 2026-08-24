# Phase 16 — Machine Learning
## Plateforme quantitative de trading crypto — V1

**Statut : Phase 16 en cours de validation.**
**Prérequis : Phases 1 à 15 validées.**

---

## 1. Garde-fou de cohérence (relecture obligatoire des phases précédentes)

La Phase 1 pose que le ML doit venir enrichir le moteur à règles **une fois celui-ci validé par plusieurs semaines de paper trading réel** — répété explicitement en conclusion de la Phase 15. Aucune semaine de paper trading réel ne s'est écoulée à ce stade (le code vient d'être écrit, pas exploité). Décision validée avec vous : **construire l'infrastructure ML maintenant, la garder désactivée par défaut**, sans jamais la brancher sur le flux de décision live tant que la validation empirique n'a pas eu lieu.

**Garde-fou technique, pas seulement documentaire** : `ML_ENABLED=false` par défaut (§7), et surtout — **aucun code de cette phase n'est appelé par `decision_engine` ou `strategies`**. Même en passant `ML_ENABLED=true` par erreur, rien ne changerait dans le flux live : le branchement réel est une action de code volontaire, différée à une phase future explicitement dédiée, pas un interrupteur de configuration.

---

## 2. Correction préalable : `pyproject.toml` manquant

Le CI (Phase 5, `ci.yml`) appelle `poetry install` depuis le début, mais aucun `pyproject.toml` n'a jamais été livré — un oubli qui aurait bloqué le tout premier pipeline. Corrigé ici, à l'occasion de l'ajout d'une vraie nouvelle dépendance (scikit-learn), en listant rétroactivement toutes les dépendances utilisées depuis la Phase 6.

---

## 3. Besoin métier de cette phase

Préparer la capacité du système à comparer plusieurs modèles prédictifs et sélectionner objectivement le meilleur (brief initial), sans jamais compromettre la garantie centrale de la Phase 1/2 : le système reste, en l'état, **entièrement déterministe et auditable**.

## 4. Périmètre retenu (sophistication progressive, cohérent Phase 1)

- **Modèles implémentés en V1** : Gradient Boosting et Random Forest (scikit-learn) — rapides à entraîner, pas de dépendance lourde (pas de PyTorch/TensorFlow à ce stade). LSTM/Transformer/TFT sont différés : ils demandent une infrastructure de calcul et une taille de dataset que le projet n'a pas encore justifiées empiriquement.
- **Label d'entraînement** : rendement futur sur un horizon configurable (ex. 10 candles 1m), binarisé (hausse/baisse au-delà d'un seuil) — cohérent avec l'horizon minute/heure de la Phase 1.
- **Entrées du modèle** : les features déjà versionnées (Phase 9) — aucune nouvelle feature ad hoc, pour garder une seule source de vérité sur ce qui alimente le système.
- **Comparaison objective** : chaque modèle est entraîné sur une période, évalué sur une période de validation disjointe, et comparé via des métriques déjà existantes (`profit_factor`, `expectancy` — réutilisées de `backtesting/metrics.py`, Phase 14, sur des trades simulés à partir des prédictions) plutôt que de dupliquer une logique d'évaluation.

---

## 5. Stockage des modèles entraînés

Nouvelle table `ml_models` (migration `0005`) : nom, version, algorithme, date d'entraînement, métriques (JSONB), modèle sérialisé (`BYTEA`), et surtout **`is_active` toujours `FALSE` en V1** — aucune ligne de code de cette phase ne met jamais ce champ à `TRUE`. L'activer serait un acte humain délibéré, dans une phase future dédiée, après revue des métriques de comparaison.

---

## 6. Fichiers produits dans cette phase

- `backend/pyproject.toml` — correction du manque (§2).
- `backend/migrations/versions/0005_add_ml_models.py`.
- `backend/shared/ml_model.py` — contrat `MLModel`.
- `backend/ml_engine/label_builder.py` — construction du label (fonction pure).
- `backend/ml_engine/models/gradient_boosting.py`, `random_forest.py`.
- `backend/ml_engine/comparison.py` — comparaison objective, sélection du meilleur.
- `backend/ml_engine/training_pipeline.py` — orchestration (lecture DB, entraînement, persistance).
- `backend/tests/test_label_builder.py`, `test_ml_models.py`, `test_ml_comparison.py`.

---

## 7. Configuration

```
ML_ENABLED=false
```
Ajoutée à `.env.example` par prudence de configuration future, **mais sans aucun effet actuellement** (§1) — aucun module ne la lit encore.

---

## 8. Auto-évaluation

**Faiblesses identifiées :**
- Stocker le modèle sérialisé en `BYTEA` dans PostgreSQL est simple et suffisant pour des modèles gradient boosting/random forest de petite taille en V1 ; deviendrait inadapté pour des modèles de deep learning volumineux (LSTM/Transformer) — à revoir si/quand ces modèles sont introduits.
- L'évaluation par `profit_factor`/`expectancy` sur des trades simulés à partir des seules prédictions ne remplace pas un vrai backtest bout-en-bout (Phase 14) intégrant risque et coûts réels — suffisant pour comparer des modèles entre eux, pas pour valider une mise en production.

**Cohérence avec les phases précédentes :** ✅ aucune modification de `decision_engine`, `strategies`, ou du flux live ; réutilisation des métriques de la Phase 14 plutôt que duplication.

---

## 9. Prochaine étape

Phase 17 — Optimisation automatique : comparaison objective de plusieurs **stratégies** (pas seulement de modèles ML) et allocation dynamique de capital entre elles — la phase pour laquelle la Phase 10 avait explicitement réservé ce rôle.
