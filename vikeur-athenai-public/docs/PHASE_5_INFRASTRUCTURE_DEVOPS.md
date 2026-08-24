# Phase 5 — Infrastructure DevOps
## Plateforme quantitative de trading crypto — V1

**Statut : Phase 5 en cours de validation.**
**Prérequis : Phases 1 à 4 validées.**
**Rappel du périmètre hérité** : monolithe modulaire (Phase 2), VPS unique Fornex (Phase 3), PostgreSQL/TimescaleDB + Redis (Phase 3/4).

---

## 1. Besoin métier de cette phase

Avec du capital réel en jeu à terme, un déploiement manuel (copier des fichiers à la main, redémarrer des services au hasard) est un risque inacceptable : une erreur de déploiement peut laisser le système dans un état incohérent pendant que des positions sont ouvertes. Il faut un processus de déploiement **reproductible, testé automatiquement avant chaque mise en production, et réversible en cas de problème**.

## 2. Problème technique

Comment automatiser la construction, les tests et le déploiement d'un monolithe modulaire (Phase 2) vers un VPS unique (Fornex, Phase 3), sans complexité excessive pour un opérateur seul, tout en garantissant qu'aucune régression ne parte en production sans être détectée ?

---

## 3. Options envisagées

### 3.1 Plateforme CI/CD
| Option | Avantages | Limites | Retenue ? |
|---|---|---|---|
| **GitHub Actions** | Gratuit pour dépôts privés dans une limite large, intégré directement au dépôt (déjà prévu dans le brief initial), pas de service tiers à gérer | Minutes limitées sur le plan gratuit (largement suffisant pour un monolithe V1) | **✅ Retenue** |
| GitLab CI | Très complet | Nécessiterait de migrer le dépôt vers GitLab | ❌ Rejetée (sans bénéfice ici) |
| Déploiement manuel scripté (sans CI) | Simple à comprendre | Aucune garantie que les tests passent avant déploiement — contraire à l'exigence de fiabilité de la Phase 1 | ❌ Rejetée |

### 3.2 Stratégie de déploiement vers le VPS
| Option | Avantages | Limites | Retenue ? |
|---|---|---|---|
| **Build en CI → push vers un registre d'images (GHCR) → SSH sur le VPS → pull + redémarrage via Docker Compose** | Reproductible, image identique testée en CI et déployée en prod, rollback simple (retag d'une image précédente) | Léger temps d'indisponibilité au redémarrage des conteneurs | **✅ Retenue** |
| Watchtower (mise à jour automatique dès qu'une nouvelle image est disponible) | Zéro action manuelle | Redémarrage non maîtrisé dans le temps — dangereux si une position est en cours de gestion au moment du redémarrage | ❌ Rejetée (perte de contrôle sur le *quand*) |
| Blue/Green ou rolling deployment | Zéro downtime | Nécessite au minimum 2 instances du backend en parallèle — sur-dimensionné pour un VPS unique et un capital <10k$ | ❌ Différée (Phase 20 si le besoin de zéro-downtime est démontré) |

**Décision retenue** : build + push vers GHCR (GitHub Container Registry) en CI, déploiement déclenché **manuellement** (validation explicite avant chaque mise en production, pas d'auto-déploiement continu) via un script SSH qui exécute `docker compose pull && docker compose up -d`.

**Justification du déploiement manuel plutôt qu'automatique** : avec du capital réel, chaque mise en production doit être une décision consciente, pas un effet de bord d'un `git push`. Le pipeline CI valide automatiquement (tests, lint), mais le **déclenchement du déploiement reste un acte volontaire** — cohérent avec la philosophie de kill switch et de contrôle humain définie en Phase 1/2.

**Gestion de l'indisponibilité au redémarrage** : le redémarrage des conteneurs entraîne une coupure de quelques secondes à quelques dizaines de secondes. Pour éviter tout risque de position orpheline (exigence de la Phase 1), le Moteur d'exécution (Phase 2, §4.7) doit **toujours reconstruire son état à partir de la base de données au démarrage** (positions ouvertes, ordres en attente) avant de reprendre toute nouvelle décision — principe déjà cohérent avec l'architecture stateless du moteur définie en Phase 2.

---

## 4. Stratégie de tests automatisés

| Niveau | Outil | Ce qui est vérifié |
|---|---|---|
| Style/format | `ruff` + `black` (Python), `eslint` + `prettier` (frontend) | Cohérence de style, erreurs évidentes |
| Typage statique | `mypy` (Python), TypeScript compiler (frontend) | Erreurs de type avant exécution |
| Tests unitaires | `pytest` | Chaque module testé indépendamment (Feature Builder, Moteur de décision, Moteur de risque, etc. — cohérent avec l'indépendance modulaire de la Phase 2) |
| Tests d'intégration | `pytest` + conteneurs de test (Postgres/Redis éphémères) | Le flux complet (collecte → features → décision → risque → exécution simulée) fonctionne de bout en bout |
| **Tests d'architecture** | `import-linter` | Vérifie automatiquement qu'aucun module n'importe directement un autre module en violation des frontières définies en Phase 2 (ex. le Moteur de décision ne doit jamais importer le module d'exécution) — répond directement à la faiblesse identifiée dans l'auto-évaluation de la Phase 2 |

**Règle de fusion (merge)** : aucune fusion vers `main` n'est autorisée si l'un de ces contrôles échoue (protection de branche GitHub).

---

## 5. Fichiers produits dans cette phase

- `infra/docker-compose.yml` — orchestration complète des services.
- `backend/Dockerfile`, `frontend/Dockerfile` — images de production.
- `.github/workflows/ci.yml` — lint, typage, tests, tests d'architecture sur chaque pull request.
- `.github/workflows/build-and-push.yml` — build + push des images vers GHCR sur fusion dans `main`.
- `infra/deploy.sh` — script de déploiement manuel exécuté depuis votre machine (SSH vers le VPS Fornex).
- `infra/.env.example` — modèle de configuration (sans secrets réels).
- `backend/importlinter.ini` — règles de frontières entre modules (Phase 2).

---

## 6. Interactions avec le reste du système

- Le `docker-compose.yml` matérialise exactement la topologie réseau définie en Phase 3 (reverse proxy exposé, backend/DB/Redis sur réseau interne).
- Les services du monolithe (Phase 2) tournent dans **un seul conteneur backend** (le monolithe modulaire n'est pas éclaté en conteneurs séparés — cohérent avec la décision de la Phase 2), tandis que PostgreSQL/TimescaleDB, Redis, le reverse proxy et le frontend sont des conteneurs distincts.
- Le script de sauvegarde défini en Phase 3 (§6) est intégré comme un service planifié dans le même `docker-compose.yml`.

---

## 7. Auto-évaluation

**Faiblesses identifiées :**
- Le déploiement manuel demande une discipline (ne pas déployer "vite fait" sans relire le changelog). *Mitigation* : le script `deploy.sh` affiche systématiquement les changements (diff des tags d'image) avant de demander confirmation.
- `import-linter` ne détecte que les violations d'import Python ; il ne garantit pas à lui seul l'absence de couplage logique plus subtil (état partagé, etc.). Point à surveiller en Phase 19 (monitoring) et lors des revues de code futures.

**Risques de conception :**
- Le temps d'indisponibilité au redémarrage (quelques secondes à dizaines de secondes) reste un point d'attention si un redémarrage tombe pendant un mouvement de marché rapide. *Mitigation actuelle* : reconstruction d'état au démarrage (§3.2) + déploiement toujours déclenché manuellement à un moment choisi (jamais en pleine nuit sans supervision, en V1).

**Cohérence avec les phases précédentes :** ✅ topologie conforme à la Phase 3, modules conformes à la Phase 2, tests d'architecture opérationnalisent directement une mitigation identifiée dans l'auto-évaluation de la Phase 2.

---

## 8. Prochaine étape

Phase 6 — Base de données : DDL réel (migrations SQL), implémentation physique du modèle défini en Phase 4, outil de migration (Alembic).
