# Phase 2 — Architecture logicielle
## Plateforme quantitative de trading crypto — V1

**Statut : Phase 2 en cours de validation.**
**Prérequis : Phase 1 (vision produit) validée.**
**Rappel du périmètre V1** : 1 exchange au départ (adapter extensible), 5-15 paires liquides, moteur de décision à règles explicites (ML différé en Phase 16), Docker Compose (pas de K8s/Kafka en V1), PostgreSQL/TimescaleDB + Redis.

---

## 1. Besoin métier de cette phase

Avant d'écrire une seule ligne de code, il faut un plan qui garantisse que :
- chaque module peut être développé, testé et remplacé **indépendamment** des autres ;
- les données circulent dans un sens clair, sans dépendances circulaires ;
- le même moteur de décision fonctionne à l'identique en **backtest**, **paper trading** et **réel** — seule la couche d'exécution change ;
- l'ajout futur d'un exchange, d'une stratégie ou d'un modèle ML ne touche jamais le cœur du système.

C'est le problème technique central de cette phase : **où placer les frontières entre les modules** pour que chacune de ces garanties tienne dans la durée.

---

## 2. Options d'architecture globale envisagées

| Option | Description | Avantages | Limites | Retenue ? |
|---|---|---|---|---|
| **A. Monolithe modulaire** | Un seul service Python, mais découpé en modules internes strictement séparés (packages), communiquant par interfaces claires | Simple à déployer et déboguer seul ; pas de complexité réseau ; cohérent avec "infra minimale" | Nécessite une discipline stricte pour ne pas recréer un "big ball of mud" | **✅ Retenue pour la V1** |
| **B. Microservices dès le départ** | Un service par module (collecteur, feature builder, moteur de décision, exécution...), communiquant en réseau (HTTP/gRPC/queue) | Scalabilité indépendante, isolation forte | Complexité opérationnelle énorme pour un opérateur seul (déploiement, observabilité inter-services, latence réseau) ; contraire à la contrainte "infra minimale" de la Phase 1 | ❌ Rejetée en V1, réévaluée en Phase 20 si le besoin de scale apparaît |
| **C. Event-driven complet (bus d'événements)** | Tous les modules communiquent uniquement via un bus d'événements (Kafka ou équivalent) | Découplage maximal, bon pour montée en charge | Sur-ingénierie pour le volume V1 ; complexité de debug (traçage asynchrone) sans bénéfice immédiat | ❌ Rejetée en V1 |

**Décision retenue : Option A — monolithe modulaire**, avec un point important : les frontières entre modules sont conçues **comme si** elles allaient un jour devenir des frontières réseau (interfaces explicites, pas de partage d'état global, pas d'accès direct à la base d'un module à l'autre). Cela permet une migration vers l'option B plus tard, module par module, sans réécriture — seulement en remplaçant l'appel de fonction interne par un appel réseau. C'est le principe du **"modular monolith as a stepping stone to microservices"**, un pattern reconnu et adapté à un contexte solo/petit capital qui doit néanmoins rester scalable dans le temps.

Un sous-choix mérite d'être tranché ici : la communication interne entre modules asynchrones (ex. collecteur → feature builder) passera par **Redis Pub/Sub** en V1 (déjà présent pour le cache), plutôt que par appel de fonction direct. Comparaison :

| Mécanisme | Avantage | Limite | Retenu ? |
|---|---|---|---|
| Appel de fonction direct (in-process) | Le plus simple | Couplage fort, impossible à faire évoluer vers plusieurs processus sans réécriture | ❌ |
| Redis Pub/Sub | Découplage réel, migration facile vers plusieurs processus/services plus tard, coût d'infra nul (Redis déjà prévu) | Pas de garantie de livraison persistante (acceptable en V1 : on ajoute une re-lecture depuis la DB en cas de perte) | **✅ Retenue** |
| Kafka | Garantie de livraison forte, rejouabilité complète | Sur-dimensionné pour le volume V1, coût opérationnel important | ❌ Différé (Phase 20+ si volume le justifie) |

---

## 3. Vue d'ensemble — les couches du système

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND (Next.js)                       │
│        Dashboard : positions, PnL, logs, config, kill switch    │
└───────────────────────────────┬───────────────────────────────---┘
                                 │ HTTP/REST + WebSocket
┌───────────────────────────────▼─────────────────────────────────┐
│                     API BACKEND (FastAPI)                       │
│   Auth · Config · Lecture des données · Contrôle manuel (kill)  │
└───────────────────────────────┬───────────────────────────────---┘
                                 │
┌───────────────────────────────▼─────────────────────────────────┐
│                      CŒUR DU MOTEUR (Python)                    │
│                                                                   │
│  ┌───────────┐  ┌──────────┐  ┌───────────┐  ┌────────────────┐ │
│  │ Collecteur │→│Normalizer│→│  Feature   │→│ Moteur de       │ │
│  │ de données │  │          │  │  Builder   │  │ décision       │ │
│  └───────────┘  └──────────┘  └───────────┘  └───────┬────────┘ │
│                                                        │          │
│                                              ┌─────────▼───────┐ │
│                                              │  Moteur de risque │ │
│                                              │  (validation)     │ │
│                                              └─────────┬───────┘ │
│                                                        │          │
│                         ┌──────────────────────────────▼───────┐│
│                         │   Moteur d'exécution (Backtest /      ││
│                         │   Paper / Réel — interface commune)   ││
│                         └──────────────────┬─────────────────---┘│
└────────────────────────────────────────────┼─────────────────---─┘
                                              │
┌─────────────────────────────────────────────▼───────────────────┐
│         STOCKAGE : PostgreSQL/TimescaleDB (historique)          │
│                  Redis (cache, temps réel, pub/sub)              │
└───────────────────────────────────────────────────────────────---┘
                                              │
┌─────────────────────────────────────────────▼───────────────────┐
│     MONITORING & JOURNAL : logs structurés, alertes, métriques  │
│         (transverse à tous les modules ci-dessus)                │
└───────────────────────────────────────────────────────────────---┘
```

---

## 4. Modules et responsabilités

### 4.1 Collecteur de données (`data_collector`)
- **Responsabilité unique** : se connecter aux exchanges (REST + WebSocket), récupérer prix, order book, trades, funding rate, et les publier vers le Normalizer.
- **Ne fait jamais** : de calcul, de décision, de stockage direct en base métier (il écrit uniquement dans une zone brute/raw).
- **Interface exposée** : `ExchangeAdapter` (contrat commun à tous les exchanges — voir §6).
- **Dépend de** : rien en interne (module le plus en amont).
- **Dont dépendent** : Normalizer.

### 4.2 Normalizer (`data_normalizer`)
- **Responsabilité** : convertir les formats hétérogènes de chaque exchange vers un schéma unique interne (mêmes noms de champs, mêmes unités, même granularité temporelle).
- **Dépend de** : Collecteur (lit les données brutes).
- **Dont dépendent** : stockage historique, Feature Builder.

### 4.3 Stockage historique (`market_data_store`)
- **Responsabilité** : persister les données normalisées (TimescaleDB), garantir l'intégrité (pas de trous silencieux, détection de gaps).
- **Dépend de** : Normalizer.
- **Dont dépendent** : Feature Builder, Backtest engine, Dashboard (lecture seule via API).

### 4.4 Feature Builder (`feature_engine`)
- **Responsabilité** : calculer les variables exploitables (order flow, volatilité, spread, indicateurs...) à partir des données stockées, avec **versionnement explicite** de chaque définition de feature.
- **Dépend de** : Stockage historique.
- **Dont dépend** : Moteur de décision.
- **Contrainte de conception** : une feature est une fonction pure (mêmes données en entrée → même résultat), pour garantir que backtest et réel produisent des résultats identiques sur les mêmes données.

### 4.5 Moteur de décision (`decision_engine`)
- **Responsabilité** : à partir des features, calculer un score par actif (probabilité de succès, espérance mathématique, ratio rendement/risque), et décider s'il y a signal ou non.
- **Dépend de** : Feature Builder.
- **Dont dépend** : Moteur de risque (jamais l'exécution directement — voir §5, principe de séparation stricte).
- **Contrainte de conception majeure** : ce module ne connaît **aucun** détail d'exécution (pas d'exchange, pas de mode backtest/paper/réel) — il ne fait que scorer et proposer.

### 4.6 Moteur de risque (`risk_engine`)
- **Responsabilité** : valider ou rejeter chaque proposition du moteur de décision (position sizing, exposition max, liquidité, perte journalière déjà atteinte, kill switch actif). **Dernier rempart avant exécution.**
- **Dépend de** : Moteur de décision (reçoit ses propositions), Stockage (positions actuelles, historique des pertes).
- **Dont dépend** : Moteur d'exécution (uniquement les ordres déjà validés).
- **Contrainte de conception majeure** : ce module a un **droit de veto absolu** et ne peut pas être contourné, même par un bug du moteur de décision — c'est un module indépendant, pas une simple fonction appelée en option.

### 4.7 Moteur d'exécution (`execution_engine`)
- **Responsabilité** : exécuter les ordres validés, dans l'un des 3 modes strictement interchangeables :
  - **Backtest** : rejoue des données historiques, simule l'exécution.
  - **Paper** : utilise des données live, simule l'exécution sans capital réel.
  - **Réel** : envoie de vrais ordres via l'`ExchangeAdapter`.
- **Dépend de** : Moteur de risque (ordres déjà validés), `ExchangeAdapter`.
- **Contrainte de conception majeure** : les 3 modes implémentent la **même interface** (`ExecutionMode`), pour que le moteur de décision et le moteur de risque n'aient **aucune connaissance** du mode actif. C'est ce qui garantit que "ce qui est testé est bien ce qui tourne en réel" (exigence de la Phase 1).

### 4.8 Journal & Monitoring (`journal` + `monitoring`)
- **Responsabilité** : enregistrer chaque décision (prise ou rejetée) avec toutes les valeurs ayant mené à ce résultat ; exposer des métriques (uptime, latence, erreurs) ; déclencher des alertes.
- **Dépend de** : tous les autres modules lui envoient des événements (il ne dépend d'aucun en retour — module purement transverse, en "écoute").
- **Conception** : implémenté comme un **abonné** (subscriber) sur le bus Redis Pub/Sub — chaque module publie ses événements, le journal les persiste, sans lien direct de code entre eux.

### 4.9 API Backend (`api`)
- **Responsabilité** : exposer en lecture les données du système (positions, PnL, logs, scores) au Dashboard, et exposer les actions manuelles autorisées (kill switch, changement de configuration).
- **Dépend de** : Stockage, Journal (lecture seule).
- **Ne dépend jamais** : n'appelle jamais directement le moteur de décision ou d'exécution — toute action passe par des commandes validées par le moteur de risque.

### 4.10 Dashboard (`frontend`)
- **Responsabilité** : interface de supervision (lecture des données via l'API, actions limitées).
- **Dépend de** : API Backend uniquement.

---

## 5. Flux de données de bout en bout

### 5.1 Flux principal (mode réel ou paper)
```
Exchange (WebSocket/REST)
   → Collecteur (raw data)
   → Normalizer (format interne unifié)
   → Stockage historique (TimescaleDB) ─┐
                                         ↓
                                  Feature Builder
                                         ↓
                                  Moteur de décision  → Journal (décision proposée)
                                         ↓
                                  Moteur de risque     → Journal (validé/rejeté + raison)
                                         ↓ (si validé)
                                  Moteur d'exécution (mode réel ou paper)
                                         ↓
                                  Exchange (ordre réel) ou simulateur (paper)
                                         ↓
                                  Stockage (position/PnL mis à jour) → Dashboard
```

### 5.2 Flux backtest (asynchrone, à la demande)
```
Stockage historique (données passées)
   → Feature Builder (rejoue sur la période choisie)
   → Moteur de décision (identique au flux réel)
   → Moteur de risque (identique)
   → Moteur d'exécution en mode Backtest (simulation d'ordres + frais + slippage estimé)
   → Rapport de performance (Sharpe, Sortino, Max Drawdown, etc. — détaillé en Phase 14)
```

**Point de conception clé** : les flux 5.1 et 5.2 partagent **exactement** le Feature Builder, le Moteur de décision et le Moteur de risque. Seul le Moteur d'exécution change de mode. C'est la garantie architecturale que backtest, paper et réel restent cohérents entre eux (critère de succès n°4 de la Phase 1).

---

## 6. Interfaces (contrats) définies à ce stade

Ces interfaces sont définies en tant que **contrats logiciels** (pas encore de code d'implémentation — cela viendra dans les phases dédiées à chaque module) :

- **`ExchangeAdapter`** : contrat que tout connecteur d'exchange doit respecter (méthodes génériques : récupérer prix, order book, envoyer ordre, annuler ordre, récupérer solde). Permet d'ajouter un exchange sans toucher au reste du système (pattern *Adapter*).
- **`Feature`** : contrat qu'une feature doit respecter (entrée = données normalisées, sortie = valeur numérique, + un identifiant de version). Permet d'ajouter/modifier des features sans casser la reproductibilité des backtests passés.
- **`Strategy`** : contrat qu'une stratégie doit respecter (entrée = scores/features, sortie = proposition de position). Permet de faire tourner plusieurs stratégies en parallèle et de les comparer objectivement (pattern *Strategy*), en cohérence avec la Phase 10.
- **`ExecutionMode`** : contrat commun aux 3 modes d'exécution (backtest/paper/réel), déjà détaillé en §4.7.
- **`RiskCheck`** : contrat que chaque règle de risque doit respecter (entrée = proposition + état du portefeuille, sortie = validé/rejeté + raison), pour pouvoir ajouter des règles de risque indépendamment les unes des autres (pattern *Chain of Responsibility*).

---

## 7. Graphe de dépendances (validation d'absence de cycle)

```
Collecteur → Normalizer → Stockage → Feature Builder → Moteur de décision
                                                              ↓
                                                       Moteur de risque
                                                              ↓
                                                    Moteur d'exécution → Exchange
                                                              ↓
                                                          Stockage (écriture positions)

Journal/Monitoring : abonné passif à tous les modules (aucune dépendance entrante)
API Backend : dépend de Stockage + Journal uniquement (lecture)
Frontend : dépend de l'API uniquement
```

Aucune dépendance circulaire : chaque flèche va dans un seul sens. Le seul flux qui "revient en arrière" (Exécution → Stockage) est une écriture de résultat, pas un appel de logique métier — distinction importante qui évite le couplage.

---

## 8. Arborescence de dépôt proposée (haut niveau)

```
projet-quant/
├── backend/
│   ├── data_collector/       # connecteurs exchange (ExchangeAdapter par exchange)
│   ├── data_normalizer/
│   ├── market_data_store/    # accès TimescaleDB
│   ├── feature_engine/       # features versionnées
│   ├── decision_engine/      # scoring, règles quantitatives
│   ├── risk_engine/          # validation, kill switch
│   ├── execution_engine/     # backtest / paper / réel (interface commune)
│   ├── journal/              # persistance des décisions et événements
│   ├── monitoring/           # métriques, alertes
│   ├── api/                  # FastAPI, endpoints lecture + actions
│   └── shared/                # contrats communs (interfaces §6), types partagés
├── frontend/                  # Next.js dashboard
├── infra/                     # Docker Compose, scripts de déploiement (Phase 5)
├── tests/                     # tests par module + tests d'intégration bout-en-bout
└── docs/                      # ce cahier des charges et les phases suivantes
```

*(Cette arborescence sera détaillée fichier par fichier au moment de l'implémentation de chaque module, phase par phase — conformément à la méthodologie imposée.)*

---

## 9. Auto-évaluation de cette phase

**Faiblesses identifiées :**
- Le choix Redis Pub/Sub pour la communication interne introduit un risque de perte de message en cas de crash (pas de persistance native). *Mitigation prévue* : le Journal relit systématiquement l'état depuis PostgreSQL au redémarrage pour détecter les incohérences — à détailler en Phase 6/19.
- Le monolithe modulaire demande une discipline stricte : rien n'empêche techniquement un développeur (moi y compris, dans les phases futures) d'importer directement un module interne au lieu de passer par l'interface prévue. *Mitigation* : des tests d'architecture (vérification automatique des imports autorisés) seront mis en place en Phase 5 (CI/CD).

**Risques de conception :**
- Si le volume de données ou le nombre d'exchanges croît plus vite que prévu, la migration vers des microservices devra être anticipée plus tôt que la Phase 20. Le pattern retenu (frontières déjà nettes) rend cette migration incrémentale, module par module — pas un big-bang.

**Cohérence avec la Phase 1 :** ✅ le découpage respecte le périmètre V1 validé (1 exchange, infra minimale, règles avant ML) tout en préparant l'extensibilité vers la vision long terme.

---

## 10. Prochaine étape

Phase 3 — Architecture cloud : décider où et comment héberger ce monolithe modulaire (VPS unique vs. cloud managé léger), en cohérence avec la contrainte de coût de la Phase 1 (quelques dizaines d'euros/mois).
