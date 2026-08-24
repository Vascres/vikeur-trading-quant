# Phase 6 — Base de données
## Plateforme quantitative de trading crypto — V1

**Statut : Phase 6 en cours de validation.**
**Prérequis : Phases 1 à 5 validées.**
**Rappel** : cette phase implémente physiquement le modèle logique défini en Phase 4 (entités, hypertables, versionnement, rétention) sur PostgreSQL/TimescaleDB (Phase 2/3).

---

## 1. Besoin métier de cette phase

Le modèle conceptuel de la Phase 4 doit devenir une base de données réelle, créée et modifiée de façon **reproductible et traçable** (jamais de modification manuelle "à la main" sur la base de production — un tel geste, avec du capital réel en jeu, est une source d'incohérence non auditable).

## 2. Problème technique

Comment appliquer, faire évoluer et versionner le schéma physique (tables classiques + hypertables TimescaleDB + politiques de compression/rétention) de façon fiable, testable en CI (Phase 5), et cohérente entre l'environnement de développement et le VPS de production (Fornex) ?

---

## 3. Options d'outillage de migration

| Option | Avantages | Limites | Retenue ? |
|---|---|---|---|
| **Alembic** (écosystème SQLAlchemy/Python) | Intégré naturellement au backend Python (Phase 2), migrations versionnées en code Python, supporte le SQL brut nécessaire aux spécificités TimescaleDB (hypertables, continuous aggregates) | Nécessite d'écrire du SQL brut pour les fonctionnalités TimescaleDB (pas de support natif) — acceptable, c'est explicite plutôt que magique | **✅ Retenue** |
| Flyway | Très robuste, largement utilisé en entreprise | Écosystème Java, ajoute une dépendance technologique supplémentaire pour un backend Python | ❌ Rejetée (cohérence stack) |
| Scripts SQL manuels versionnés dans Git (sans outil dédié) | Simple | Pas de suivi automatique de l'état appliqué, risque d'appliquer deux fois ou d'oublier une migration | ❌ Rejetée (pas assez fiable) |

**Décision retenue : Alembic**, avec les commandes spécifiques TimescaleDB (`create_hypertable`, `add_compression_policy`, `add_retention_policy`, `CREATE MATERIALIZED VIEW ... WITH (timescaledb.continuous)`) exécutées en SQL brut à l'intérieur des migrations Alembic (via `op.execute`) — Alembic gère l'orchestration et l'historique, TimescaleDB reste piloté en SQL natif, sans abstraction risquée.

---

## 4. Contenu de la migration initiale

La migration `0001_initial_schema` crée, dans l'ordre (respect des dépendances de clés étrangères) :

1. Extension `timescaledb`.
2. Tables de définitions versionnées : `feature_definitions`, `strategies` (jamais modifiées après création — Phase 4, §5.2/5.3).
3. Hypertables de marché : `raw_market_data`, `order_book_snapshots`, `funding_rates`, `feature_values`.
4. `ohlcv_candles` en **continuous aggregate** (vue matérialisée maintenue automatiquement par TimescaleDB à partir de `raw_market_data`), pas une table à remplir manuellement.
5. Tables relationnelles classiques : `decisions`, `risk_checks`, `orders`, `positions`, `events_journal`, `backtest_runs`, `backtest_results`.
6. Politiques de compression et de rétention, exactement conformes au tableau de la Phase 4, §6.

---

## 5. Interactions avec le reste du système

- Le backend (Phase 2) utilise `DATABASE_URL` (déjà défini dans `.env`, Phase 5) pour se connecter ; Alembic utilise la même URL pour appliquer les migrations.
- Les migrations sont exécutées **avant** le démarrage du conteneur backend en production (étape ajoutée au script `deploy.sh` de la Phase 5 — voir §7).
- Le CI (Phase 5) applique déjà les migrations sur une base Postgres/Timescale éphémère avant de lancer les tests d'intégration.

---

## 6. Tests de cette phase

- **Test de migration "aller"** : la migration s'applique sans erreur sur une base vierge (déjà exécuté implicitement par le CI, Phase 5).
- **Test de migration "retour" (downgrade)** : chaque migration doit pouvoir être annulée proprement — vérifié explicitement en test.
- **Test de contraintes** : vérifier qu'un `order` sans `risk_check_id` valide est rejeté par la base (contrainte de clé étrangère non nullable — traçabilité de la Phase 4, §7).
- **Test des politiques TimescaleDB** : vérifier via une requête sur les catalogues internes (`timescaledb_information.hypertables`, `.jobs`) que les hypertables et les politiques de compression/rétention sont bien actives après migration.

---

## 7. Mise à jour du script de déploiement (Phase 5)

Le script `deploy.sh` doit exécuter les migrations avant de redémarrer le service backend. Ajout prévu (à intégrer dans la version suivante du script) :
```
ssh "${VPS_HOST}" "cd ${REMOTE_DIR} && docker compose run --rm backend alembic upgrade head"
```
placé juste après le `docker compose pull` et avant le `docker compose up -d`, pour garantir que le schéma est à jour avant que le nouveau code ne démarre.

---

## 8. Auto-évaluation

**Faiblesses identifiées :**
- Les migrations contenant du SQL brut TimescaleDB (hypertables, continuous aggregates) sont moins "portables" que du SQLAlchemy pur — c'est un choix assumé (§3) car ces fonctionnalités n'ont pas d'équivalent abstrait fiable ; documenté explicitement dans chaque migration.
- Une seule migration initiale regroupe beaucoup de tables : pour la suite du projet, chaque évolution de schéma devra être une migration Alembic dédiée et atomique (une modification = une migration), pas des ajouts groupés.

**Risques de conception :**
- Les continuous aggregates TimescaleDB ont une politique de rafraîchissement (refresh policy) à calibrer : trop fréquente = charge inutile, trop rare = candles pas à jour pour le moteur de décision temps réel. Valeur initiale prudente choisie ci-dessous, à ajuster empiriquement dès la Phase 7 (collecte réelle).

**Cohérence avec les phases précédentes :** ✅ schéma physique conforme exactement au modèle logique de la Phase 4, outillage cohérent avec le choix Python (Phase 2) et le pipeline CI (Phase 5).

---

## 9. Prochaine étape

Phase 7 — Collecte des données de marché : implémentation du `data_collector` et du premier `ExchangeAdapter` (Phase 2, §4.1/§6), y compris la procédure pas à pas de création et sécurisation des clés API demandée dans le brief initial.
