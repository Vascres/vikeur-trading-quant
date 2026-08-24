# Phase 18 — Tableau de bord web
## Plateforme quantitative de trading crypto — V1

**Statut : Phase 18 en cours de validation.**
**Prérequis : Phases 1 à 17 validées.**

---

## 1. Correction préalable : le monolithe s'était fragmenté en scripts indépendants

En relisant les décisions précédentes (obligatoire à chaque phase) avant de construire l'**API Backend** (Phase 2, §4.9) dont ce tableau de bord a besoin, un écart s'est révélé : la Phase 2 avait tranché pour un **monolithe modulaire** (un seul processus backend, modules internes séparés) plutôt que des microservices, précisément pour limiter la charge opérationnelle d'un opérateur seul (Phase 3). Mais au fil des phases, j'ai livré cinq points d'entrée indépendants (`data_collector/main.py`, `data_normalizer/main.py`, `feature_engine/main.py`, `decision_engine/main.py`, `execution_engine/main.py`), et `docker-compose.yml` (Phase 5) ne prévoyait qu'**un seul conteneur** générique — sans jamais orchestrer ces cinq boucles ensemble.

**Correction retenue** : un point d'entrée unique `backend/main.py` regroupe les cinq boucles dans un seul processus (`asyncio.gather`), conforme au monolithe modulaire de la Phase 2. L'**API Backend** (FastAPI, lecture seule + actions de contrôle limitées, Phase 2 §4.9) devient un **second processus**, dans la même image Docker — c'est exactement la distinction déjà présente dans le diagramme de la Phase 2 (« Cœur du moteur » vs « API Backend », deux boîtes séparées), que `docker-compose.yml` n'avait simplement jamais matérialisée. Deux processus, une seule image : ce n'est pas un glissement vers les microservices (même code, même déploiement), juste la séparation minimale nécessaire pour que l'API reste réactive indépendamment de la charge du moteur.

---

## 2. Besoin métier de cette phase

Un tableau de bord pour superviser le système : positions, décisions, journal, performance par stratégie (Phase 17), et un contrôle manuel du kill switch (Phase 13) — sans jamais permettre d'action qui contournerait le Moteur de risque.

## 3. Périmètre retenu (V1, sophistication progressive)

Dashboard fonctionnel et sombre par défaut, pas encore « premium » visuellement — cohérent avec la Phase 1 (priorité à l'observabilité fonctionnelle, enrichissement visuel progressif) :
- Vue d'ensemble : positions ouvertes/fermées, PnL, graphique de prix (widget TradingView).
- Décisions récentes et journal (`events_journal`).
- Performance par stratégie (réutilise Phase 14/17 — pas de nouveau calcul).
- Bouton kill switch (lit/écrit directement le flag Redis, Phase 13 §4 — **la seule action d'écriture exposée**).

**Explicitement hors périmètre V1** : édition de configuration, activation ML (Phase 16 — resterait un acte volontaire hors dashboard pour l'instant), application des recommandations d'allocation (Phase 17) — leur affichage seul est en périmètre, leur application reste manuelle côté base pour l'instant.

---

## 4. Fichiers produits dans cette phase

- `backend/main.py` — point d'entrée unique du moteur (§1).
- `backend/api/main.py` — API FastAPI (positions, décisions, journal, performance, kill switch, health).
- `infra/docker-compose.yml` **(mis à jour)** — service `engine` (nouveau) + service `backend` devenu l'API.
- `frontend/` — application Next.js (dashboard).
- `backend/tests/test_api.py`.

---

## 5. Auto-évaluation

**Faiblesses identifiées :**
- Le dashboard reste fonctionnel, pas visuellement abouti — assumé (§3), cohérent avec la priorité de la Phase 1.
- Les actions d'allocation (Phase 17) et d'activation ML (Phase 16) restent hors dashboard en V1 — un choix de prudence, pas un oubli (voir garde-fous déjà posés dans ces phases).

**Cohérence avec les phases précédentes :** ✅ corrige un écart architectural réel plutôt que de construire le dashboard sur une fondation ambiguë ; respecte tous les garde-fous déjà posés (aucune action d'écriture hors kill switch).

---

## 6. Prochaine étape

Phase 19 — Monitoring et observabilité : métriques d'infrastructure (uptime, latence, erreurs), alertes proactives — au-delà de ce que le dashboard affiche déjà passivement.
