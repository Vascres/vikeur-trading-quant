# Phase 17 — Optimisation automatique
## Plateforme quantitative de trading crypto — V1

**Statut : Phase 17 en cours de validation.**
**Prérequis : Phases 1 à 16 validées.**

---

## 1. Besoin métier de cette phase

Comparer objectivement les stratégies actives, désactiver celles qui sous-performent, et faire recevoir davantage de capital aux meilleures (brief initial) — le rôle explicitement réservé à cette phase depuis la Phase 10, §3.

## 2. Correction préalable : `positions` n'était reliée à aucune stratégie

Impossible de comparer des stratégies sans savoir **quelle position appartient à quelle stratégie**. La table `positions` (Phase 6) n'a jamais porté cette information. Migration `0006` : ajout de `positions.decision_id` (→ `decisions.strategy_id`). Fil de bout en bout mis à jour : `ExecutionMode.execute()` accepte désormais `decision_id`, transmis par l'orchestrateur (Phase 13) jusqu'à `execution_engine/positions.py` (Phase 15).

## 3. Décision de conception : asymétrie entre désactivation et allocation

Deux actions très différentes en termes de risque :
- **Désactiver une stratégie qui sous-performe** réduit le risque — cohérent avec l'automatisation déjà acceptée pour le kill switch (Phase 13). **Automatisée.**
- **Donner plus de capital à une stratégie qui performe bien** augmente l'exposition réelle — cohérent avec la même prudence que l'activation ML (Phase 16, §1) : **une recommandation calculée et journalisée, jamais appliquée automatiquement** au dimensionnement réel tant qu'elle n'a pas été validée humainement (action prévue au tableau de bord, Phase 18).

Avec une seule stratégie active à ce stade (`momentum_imbalance_threshold`), il n'y a rien à comparer pour l'instant — l'infrastructure est prête pour le jour où une deuxième stratégie existera (cohérent avec le principe déjà appliqué en Phase 16 : construire avant que le besoin ne soit démontré serait prématuré, mais retarder la construction une fois le besoin identifié ne le serait pas).

---

## 4. Mécanisme

- **Score de performance** : espérance mathématique (`expectancy`, réutilisée de `backtesting/metrics.py`, Phase 14) sur les positions fermées récentes (mode paper) de chaque stratégie.
- **Désactivation automatique** : si le score est négatif sur au moins un nombre minimal de trades (évite de désactiver sur un échantillon trop petit), `strategies.is_active` passe à `FALSE`.
- **Recommandation d'allocation** : proportionnelle aux scores positifs des stratégies encore actives, normalisée, **persistée dans une nouvelle table `strategy_allocations`** (`applied = FALSE` par défaut) — jamais lue par `risk_engine` à ce stade.

---

## 5. Fichiers produits dans cette phase

- `backend/migrations/versions/0006_add_position_decision_id.py`, `0007_add_strategy_allocations.py`.
- `backend/shared/execution_mode.py`, `execution_engine/modes/*.py`, `execution_engine/main.py`, `execution_engine/positions.py` **(mis à jour)** — fil `decision_id`.
- `backend/optimization/performance_evaluator.py` — score et critère de désactivation (fonctions pures).
- `backend/optimization/capital_allocator.py` — calcul des fractions d'allocation (fonction pure).
- `backend/optimization/orchestrator.py` — orchestration DB (désactivation automatique, recommandation persistée).
- `backend/tests/test_optimization.py`.

---

## 6. Auto-évaluation

**Faiblesses identifiées :**
- Avec une seule stratégie active, cette phase ne peut pas être validée par un cas d'usage réel avant qu'une deuxième stratégie existe — assumé, cohérent avec le raisonnement du §3.
- Le nombre minimal de trades avant désactivation est une valeur de départ arbitraire, à calibrer avec l'usage réel.

**Cohérence avec les phases précédentes :** ✅ corrige un vrai trou de traçabilité (§2) plutôt que de le contourner ; applique la même asymétrie prudence-automatisation que la Phase 13 (kill switch) et la Phase 16 (ML) plutôt que d'introduire un nouveau principe.

---

## 7. Prochaine étape

Phase 18 — Tableau de bord web : interface où les recommandations d'allocation (et l'activation ML) pourront enfin être validées humainement, avec la visualisation des positions, PnL, et decisions.
