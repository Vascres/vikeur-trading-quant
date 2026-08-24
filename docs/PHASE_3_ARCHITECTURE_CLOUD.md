# Phase 3 — Architecture cloud
## Plateforme quantitative de trading crypto — V1

**Statut : Phase 3 en cours de validation.**
**Prérequis : Phases 1 (vision) et 2 (architecture logicielle) validées.**
**Rappel des contraintes héritées** : opérateur unique, capital <10k$, budget infra "quelques dizaines d'euros/mois", monolithe modulaire en Docker Compose (pas de Kubernetes), PostgreSQL/TimescaleDB + Redis.

---

## 1. Besoin métier de cette phase

Le système doit tourner **24h/24** sans surveillance humaine constante, avec du **capital réel** en jeu à terme. Il faut donc un hébergement qui garantisse :
- une disponibilité suffisante pour ne pas manquer d'événements de marché critiques (perte de connexion prolongée = risque de position non gérée) ;
- une sécurité réseau stricte (aucune base de données ni cache exposé publiquement, clés API protégées) ;
- des sauvegardes fiables, indépendantes de la machine principale (si le VPS tombe définitivement, on ne doit pas perdre l'historique ni la configuration) ;
- un coût prévisible et maîtrisé, cohérent avec un capital de trading de départ inférieur à 10k$.

## 2. Problème technique

Où et comment héberger un monolithe modulaire (backend Python + PostgreSQL/TimescaleDB + Redis + frontend Next.js) pour un opérateur seul, sans équipe SRE, tout en gardant une trajectoire d'évolution vers plus de robustesse (redondance, multi-région) si le projet grossit ?

---

## 3. Options envisagées

| Option | Description | Avantages | Limites | Retenue ? |
|---|---|---|---|---|
| **A. VPS unique (Hetzner / OVH / DigitalOcean)** | Une seule machine virtuelle, Docker Compose dessus | Coût très bas (5-20€/mois pour une config suffisante en V1), contrôle total, pas de vendor lock-in, simple à comprendre et à déboguer seul | Point de défaillance unique (SPOF) ; pas de redondance automatique ; toute la responsabilité sécurité/OS repose sur vous | **✅ Retenue pour la V1** |
| **B. Cloud managé complet (AWS/GCP/Azure avec RDS, ElastiCache, ECS...)** | Services managés pour chaque brique (base de données managée, cache managé, orchestration de conteneurs managée) | Haute disponibilité native, montée en charge facile, sauvegardes automatiques intégrées | Coût significativement plus élevé (souvent 100-300€+/mois dès qu'on active RDS + ElastiCache + un service de conteneurs) ; complexité de configuration (IAM, VPC, sécurité réseau) disproportionnée pour un seul opérateur en V1 | ❌ Rejetée en V1, réévaluée en Phase 20 si le capital géré et les revenus le justifient |
| **C. PaaS (Railway, Render, Fly.io)** | Plateforme qui gère le déploiement à partir du code, moins de gestion serveur | Très simple à mettre en place, bon pour prototyper vite | Moins de contrôle fin sur le réseau (isolation DB/Redis), coût qui grimpe vite avec des workers 24/7 et une base TimescaleDB, dépendance forte au fournisseur | ❌ Rejetée : le besoin de contrôle réseau strict (aucune exposition DB/Redis) et de coût prévisible sur le long terme favorise le VPS |
| **D. Hybride (VPS + stockage objet externe pour les backups)** | VPS pour le run, mais sauvegardes répliquées vers un stockage objet indépendant (Backblaze B2, Hetzner Storage Box, S3) | Combine le faible coût du VPS et une vraie résilience de la donnée en cas de perte totale de la machine | Aucune, c'est un complément à l'option A, pas une alternative | **✅ Retenue en complément de A** |

**Décision retenue : Option A (VPS unique) + Option D (sauvegardes externalisées).**

Justification : avec un capital <10k$ et un opérateur seul, le risque dominant n'est pas "le cloud managé tombe en panne" (peu probable de toute façon sur un VPS sérieux), c'est plutôt **la complexité opérationnelle qui dépasse ce qu'une personne peut maintenir correctement**. Un VPS bien configuré, avec sauvegardes externes et un kill switch fiable (Phase 2), couvre le vrai risque à ce stade. La bascule vers l'option B sera réévaluée explicitement en Phase 20, avec des critères objectifs (capital géré, revenus, besoin de redondance démontré).

### Choix du fournisseur VPS

**Fournisseur retenu : Fornex.** Vérification de compatibilité avec les besoins des Phases 2/3 : VPS en virtualisation KVM (isolation complète des ressources), stockage NVMe, Ubuntu 22.04/24.04 LTS disponible, Docker pré-supporté, protection DDoS incluse au niveau réseau, datacenters disponibles en Europe (dont Allemagne/Francfort) et aux États-Unis. Compatible avec l'architecture retenue (§4).

Point à trancher lors de la commande : **choisir un datacenter européen (ex. Francfort) plutôt qu'un datacenter plus éloigné**, pour minimiser la latence vers les moteurs d'appariement des exchanges (souvent en Europe de l'Ouest, à Tokyo ou aux États-Unis). Avec l'horizon de décision minute/heure défini en Phase 1, ce choix reste un point d'optimisation, pas un facteur bloquant.

L'architecture reste portable vers un autre fournisseur à tout moment grâce à Docker (aucun couplage propriétaire dans `infra/`).

---

## 4. Architecture réseau retenue

```
                         Internet
                            │
                    ┌───────▼────────┐
                    │  Reverse proxy  │   (Traefik ou Caddy)
                    │  TLS (Let's     │   → seul point d'entrée public
                    │  Encrypt auto)  │
                    └───────┬────────┘
                            │  (réseau Docker "public")
              ┌─────────────┼──────────────┐
       ┌──────▼──────┐              ┌──────▼──────┐
       │  Frontend    │              │ API Backend │
       │  (Next.js)   │              │ (FastAPI)   │
       └─────────────┘              └──────┬──────┘
                                            │ (réseau Docker "interne", non exposé)
                          ┌─────────────────┼─────────────────┐
                   ┌──────▼──────┐   ┌──────▼──────┐   ┌──────▼──────┐
                   │ Cœur moteur  │   │ PostgreSQL/  │   │   Redis     │
                   │ (Phase 2)    │   │ TimescaleDB  │   │             │
                   └─────────────┘   └─────────────┘   └─────────────┘
```

**Règles de sécurité réseau non négociables :**
- Seul le reverse proxy est exposé sur les ports 80/443. Tout le reste communique sur un réseau Docker interne, invisible depuis l'extérieur.
- PostgreSQL et Redis ne sont **jamais** accessibles depuis Internet, même avec mot de passe — uniquement depuis le réseau Docker interne.
- Le firewall du VPS (ex. `ufw` ou pare-feu du fournisseur) bloque tout port non explicitement nécessaire (SSH restreint à votre IP si possible, 80/443 uniquement).
- Accès SSH par clé uniquement (pas de mot de passe), avec un utilisateur non-root pour l'exploitation quotidienne.

---

## 5. Gestion des secrets

- Aucune clé API, mot de passe ou secret n'est écrit en dur dans le code ou commité dans le dépôt Git.
- Un fichier `.env` (non versionné, exclu via `.gitignore`) contient les secrets, avec permissions restreintes (`chmod 600`) sur le VPS.
- Les clés API des exchanges sont créées avec les **permissions minimales strictement nécessaires** : trading autorisé, **retrait de fonds toujours désactivé**. Ce point sera détaillé précisément en Phase 6/7 (comment créer et sécuriser ces clés pas à pas, comme demandé dans le brief initial).
- Piste d'amélioration future (non bloquante en V1) : migrer vers un gestionnaire de secrets dédié (ex. Vault, ou le secret manager du fournisseur cloud) si le projet passe à l'option B en Phase 20.

---

## 6. Sauvegardes et reprise après sinistre

- **Sauvegarde base de données** : dump PostgreSQL automatique quotidien (script planifié), compressé, envoyé vers un stockage objet externe (Backblaze B2 ou équivalent), avec rétention définie (ex. 30 jours glissants).
- **Sauvegarde configuration/code** : le code vit dans Git (GitHub — Phase 5), donc reconstructible à tout moment ; seuls les secrets et les données nécessitent une sauvegarde dédiée.
- **Snapshot VPS** : snapshot hebdomadaire de la machine complète proposé par le fournisseur (filet de sécurité supplémentaire, peu coûteux).
- **Plan de reprise minimal** : en cas de perte totale du VPS, la procédure est : provisionner un nouveau VPS → cloner le dépôt → restaurer le dernier dump PostgreSQL → redémarrer via Docker Compose. Ce plan sera testé concrètement (pas juste documenté) au plus tard en Phase 20.

---

## 7. Interactions avec le reste du système

- Cette phase ne modifie aucune décision de la Phase 2 (modules, interfaces) — elle définit uniquement **où** ils s'exécutent physiquement.
- Le découpage en réseaux Docker "public" / "interne" **renforce** la séparation des responsabilités définie en Phase 2 (ex. l'API ne peut techniquement pas être contournée pour accéder directement à la base depuis l'extérieur).
- Les scripts de déploiement précis (CI/CD, Dockerfiles détaillés) seront écrits en **Phase 5 — Infrastructure DevOps** ; cette phase-ci pose uniquement les choix structurants (fournisseur, topologie réseau, stratégie de sauvegarde).

---

## 8. Arborescence complétée

```
projet-quant/
├── backend/            (défini en Phase 2)
├── frontend/            (défini en Phase 2)
├── infra/
│   ├── docker-compose.yml          # orchestration complète (Phase 5)
│   ├── reverse-proxy/              # config Traefik/Caddy + TLS
│   ├── backup/                     # scripts de dump + envoi vers stockage objet
│   └── firewall/                    # règles ufw ou équivalent, documentées
├── tests/
└── docs/
    └── PHASE_3_ARCHITECTURE_CLOUD.md
```

---

## 9. Auto-évaluation

**Faiblesses identifiées :**
- Le VPS unique reste un **point de défaillance unique** assumé. Ce risque est jugé acceptable en V1 (capital <10k$, pas de SLA client) mais devra être réévalué explicitement si le capital géré augmente significativement.
- La sécurité repose entièrement sur la rigueur de configuration (pas de garde-fous managés automatiques comme chez un cloud provider). *Mitigation* : un audit de sécurité explicite est déjà prévu en Phase 20, mais un premier passage de durcissement (firewall, SSH, mises à jour automatiques) doit être fait dès la mise en service, pas reporté.

**Risques de conception :**
- Panne du fournisseur VPS (rare mais possible) : le système serait indisponible le temps de la panne. Avec un moteur qui doit rester actif 24/7, ce risque doit être communiqué clairement : en V1, on accepte un risque de downtime non redondé, compensé par un kill switch fiable et une reprise rapide (§6), pas par de la haute disponibilité.

**Cohérence avec les phases précédentes :** ✅ topologie réseau conforme au découpage modulaire de la Phase 2 ; coût conforme à la contrainte de la Phase 1.

**Amélioration future à noter** : si un second exchange ou un capital plus important est ajouté (Phase 17+), réévaluer une réplication de la base (lecture seule) sur une seconde machine, avant d'envisager un cloud managé complet.

---

## 10. Prochaine étape

Phase 4 — Architecture des données : schéma de données détaillé (marché, features, décisions, positions, journal), stratégie de partitionnement TimescaleDB, politique de rétention.
