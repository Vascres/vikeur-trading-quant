# Phase 4 — Architecture des données
## Plateforme quantitative de trading crypto — V1

**Statut : Phase 4 en cours de validation.**
**Prérequis : Phases 1, 2, 3 validées.**
**Rappel du périmètre hérité** : 1 exchange, 5-15 paires liquides, moteur à règles explicites (pas de ML en V1), PostgreSQL/TimescaleDB + Redis sur un VPS unique (Fornex).

**Note de périmètre** : cette phase définit le **modèle logique des données** (entités, relations, stratégie de partitionnement/rétention, principes de traçabilité). L'implémentation physique (DDL, migrations, scripts) est volontairement réservée à la **Phase 6 — Base de données**, pour ne pas mélanger conception et implémentation.

---

## 1. Besoin métier de cette phase

Le brief initial et la Phase 1 exigent que **chaque décision soit explicable a posteriori**. Cela veut dire concrètement : pouvoir répondre, des mois plus tard, à la question *"pourquoi le moteur a-t-il pris (ou refusé) cette position sur ETH le 14 mars à 09h32 ?"*, en retrouvant exactement les données de marché, les features calculées, le score obtenu, et la décision du moteur de risque à cet instant précis.

Cela impose une exigence forte sur le modèle de données : ce n'est pas juste "stocker des prix", c'est **stocker une chaîne de traçabilité complète et reconstituable**, tout en restant exploitable à faible coût sur un VPS unique (contrainte de la Phase 3).

## 2. Problème technique

Comment structurer les données pour que :
- l'historique de marché (potentiellement volumineux — carnets d'ordres, trades) soit stocké et interrogé efficacement dans le temps ;
- les features calculées soient **versionnées** (une feature peut évoluer ; il faut savoir avec quelle version une décision passée a été prise, pour que les backtests restent reproductibles) ;
- chaque décision, chaque validation/rejet de risque, chaque ordre soit **relié** aux données qui l'ont produit (clé de traçabilité) ;
- le volume de données ne dépasse pas ce qu'un VPS unique (Phase 3) peut gérer dans la durée, sans perdre l'information utile.

---

## 3. Options de modélisation envisagées

| Option | Description | Avantages | Limites | Retenue ? |
|---|---|---|---|---|
| **A. Tout normalisé (relationnel strict, 3NF)** | Chaque type de donnée dans sa propre table, relations strictes par clés étrangères, y compris pour les séries temporelles | Cohérence maximale, pas de duplication | Peu adapté aux séries temporelles à haute fréquence (jointures coûteuses sur de gros volumes) | ❌ Rejetée seule |
| **B. Tout "large" (wide tables, dénormalisé)** | Une table plate par flux de données avec toutes les colonnes possibles | Lecture rapide, simple | Rigide : ajouter une feature = modifier le schéma de la table à chaque fois ; casse la traçabilité par version | ❌ Rejetée |
| **C. EAV (Entity-Attribute-Value) générique pour les features** | Une table générique `(entity_id, attribute, value, timestamp)` pour stocker n'importe quelle feature sans changer le schéma | Très flexible pour ajouter des features | Requêtes complexes et lentes à volume élevé, perte de typage fort | ❌ Rejetée en table principale |
| **D. Hybride : hypertables TimescaleDB pour les séries temporelles + tables relationnelles classiques pour le reste, avec un schéma de features semi-structuré (une ligne par calcul, colonnes typées + table de définitions versionnées)** | Combine performance sur séries temporelles et flexibilité contrôlée pour les features | Bon compromis performance/flexibilité/traçabilité, cohérent avec le choix PostgreSQL/TimescaleDB déjà acté en Phase 2/3 | Demande une discipline de conception (définir clairement ce qui est hypertable vs table classique) | **✅ Retenue** |

**Décision retenue : Option D**, détaillée ci-dessous.

Justification : les données de marché (prix, carnet d'ordres, trades) sont par nature des séries temporelles à volume élevé — c'est le cas d'usage central de TimescaleDB (déjà choisi en Phase 2). Les décisions, ordres, et journaux sont en revanche des événements discrets à volume beaucoup plus faible (quelques dizaines à quelques centaines par jour en V1) — une modélisation relationnelle classique suffit largement et apporte une meilleure garantie d'intégrité (clés étrangères strictes).

---

## 4. Modèle conceptuel des données

```
┌───────────────────┐     ┌───────────────────┐
│  raw_market_data   │     │  order_book_snap   │   ← hypertables (haute fréquence)
│  (trades bruts)    │     │  (L2, périodique)  │
└─────────┬─────────┘     └─────────┬─────────┘
          │                          │
          └────────────┬─────────────┘
                        ▼
              ┌───────────────────┐
              │  ohlcv_candles     │   ← hypertable (agrégats, continuous aggregate)
              └─────────┬─────────┘
                        │
                        ▼
              ┌───────────────────┐        ┌────────────────────────┐
              │  feature_values    │◄──────│  feature_definitions    │
              │  (par actif/temps) │        │  (versionnées, figées)  │
              └─────────┬─────────┘        └────────────────────────┘
                        │
                        ▼
              ┌───────────────────┐        ┌────────────────────────┐
              │  decisions         │──────►│  strategies              │
              │  (scores, verdict) │        │  (versionnées)           │
              └─────────┬─────────┘        └────────────────────────┘
                        │
                        ▼
              ┌───────────────────┐
              │  risk_checks       │   ← relié à decisions (verdict + raison)
              └─────────┬─────────┘
                        │ (si validé)
                        ▼
              ┌───────────────────┐        ┌────────────────────────┐
              │  orders            │──────►│  positions               │
              └─────────┬─────────┘        └────────────────────────┘
                        │
                        ▼
              ┌───────────────────┐
              │  events_journal    │   ← abonné passif, référence tout ce qui précède
              └───────────────────┘

              ┌───────────────────┐
              │  backtest_runs     │   ← résultats de backtests (Phase 14), référence
              │  backtest_results  │      une version de stratégie + une période de données
              └───────────────────┘
```

---

## 5. Détail des entités principales

### 5.1 Données de marché brutes (hypertables TimescaleDB)
- **`raw_market_data`** : chaque trade exécuté sur l'exchange (prix, quantité, side, timestamp exchange, timestamp de réception). Table la plus volumineuse.
- **`order_book_snapshots`** : snapshots périodiques du carnet d'ordres (top N niveaux bid/ask), fréquence à définir en Phase 7 selon ce que l'API/WebSocket de l'exchange permet.
- **`ohlcv_candles`** : chandeliers agrégés (1m, 5m, 1h...), calculés en **continuous aggregate** TimescaleDB à partir de `raw_market_data` — pas besoin de les recalculer manuellement, TimescaleDB les maintient automatiquement à jour.
- **`funding_rates`** : taux de financement (si contrats perpétuels), fréquence basse (toutes les 1-8h selon exchange).

Toutes ces tables partagent : `exchange`, `symbol`, `timestamp` comme clé de partitionnement temporel (colonne `time` en hypertable).

### 5.2 Features (semi-structuré, versionné)
- **`feature_definitions`** : une ligne par feature *version* (nom, description, version, date de création, hash de la logique de calcul). Une fois créée, une version n'est **jamais modifiée** — toute évolution crée une nouvelle version. C'est la garantie de reproductibilité des backtests passés (exigence de la Phase 1).
- **`feature_values`** : `(feature_definition_id, exchange, symbol, timestamp, value)`. Hypertable également (volume proportionnel aux données de marché × nombre de features actives).

### 5.3 Stratégies et décisions
- **`strategies`** : une ligne par stratégie *version* (nom, paramètres, version, active/inactive). Même principe de versionnement figé que les features.
- **`decisions`** : chaque évaluation du moteur de décision (Phase 2, §4.5) — `strategy_id`, `symbol`, `timestamp`, score de probabilité, espérance mathématique calculée, verdict (signal / pas de signal), et une référence aux `feature_values` utilisées (pour la traçabilité complète).
- **`risk_checks`** : chaque validation/rejet du moteur de risque (Phase 2, §4.6) — `decision_id` (clé étrangère), règle appliquée, résultat, raison précise si rejet.

### 5.4 Exécution
- **`orders`** : chaque ordre envoyé (ou simulé), avec `risk_check_id` (traçabilité — un ordre n'existe jamais sans un risk_check validé en amont), mode (`backtest`/`paper`/`réel`), statut, prix/quantité demandés vs. exécutés, slippage réel constaté.
- **`positions`** : état agrégé des positions ouvertes/fermées, PnL réalisé/latent.

### 5.5 Journal et observabilité
- **`events_journal`** : table d'événements génériques (module source, type d'événement, payload structuré, timestamp), alimentée en continu par tous les modules via l'abonnement Redis Pub/Sub défini en Phase 2. Sert de filet de sécurité : même si une table métier spécifique manque un cas, l'événement brut reste tracé.

### 5.6 Backtesting
- **`backtest_runs`** : une exécution de backtest (période, `strategy_id` + version, paramètres, date d'exécution).
- **`backtest_results`** : métriques de performance associées (Sharpe, Sortino, Max Drawdown, etc. — détaillées en Phase 14), reliées à `backtest_runs`.

---

## 6. Stratégie de partitionnement et rétention (TimescaleDB)

| Table (hypertable) | Intervalle de chunk | Compression | Politique de rétention V1 | Justification |
|---|---|---|---|---|
| `raw_market_data` | 1 jour | Activée après 7 jours | Conserver 90 jours en détaillé, puis ne garder que les `ohlcv_candles` dérivées | Le tick-by-tick brut est volumineux et son utilité marginale décroît vite une fois les candles/features calculées ; le backtesting fin sur tick data reste possible sur les 90 derniers jours |
| `order_book_snapshots` | 1 jour | Activée après 3 jours | Conserver 30 jours en détaillé | Volume le plus élevé de toutes les tables ; utile surtout pour l'analyse récente de microstructure, moins pour le backtest long terme |
| `ohlcv_candles` | 7 jours | Activée après 30 jours | **Conservée indéfiniment** (volume faible une fois agrégé) | Base du backtest long terme (plusieurs années, exigence de la Phase 1/14) |
| `feature_values` | 1 jour | Activée après 7 jours | Alignée sur `raw_market_data`/`ohlcv_candles` selon la feature | Cohérence avec la donnée source |
| `funding_rates` | 30 jours | Non nécessaire (volume faible) | Conservée indéfiniment | Volume négligeable |
| `decisions`, `risk_checks`, `orders`, `positions`, `events_journal` | (tables relationnelles classiques, pas des hypertables) | N/A | **Conservées indéfiniment** | Volume faible (quelques centaines de lignes/jour max en V1) ; c'est précisément la donnée qui garantit l'explicabilité — elle ne doit jamais être purgée |

**Principe général retenu** : on ne supprime jamais la donnée qui sert à l'explicabilité des décisions (§5.3-5.5), et on ne réduit la granularité que sur la donnée brute de marché dont le rôle est surtout de nourrir le calcul de features et de candles — une fois ce calcul fait et vérifié, le détail tick-by-tick ancien perd l'essentiel de sa valeur pour un système à l'horizon minute/heure (Phase 1).

---

## 7. Traçabilité de bout en bout (mise en œuvre concrète du besoin de la Phase 1)

Chaîne d'identifiants permettant de reconstituer n'importe quelle décision passée :

```
decision.id
   ├─→ decision.feature_snapshot_ids[] → feature_values (valeurs exactes utilisées)
   ├─→ decision.strategy_id (+ version)  → strategies (paramètres exacts au moment T)
   ├─→ risk_checks.decision_id           → toutes les règles évaluées + verdicts
   └─→ orders.risk_check_id (si validé)  → ordre réellement envoyé/simulé
```

Cette chaîne répond directement au critère de succès n°2 de la Phase 1 ("chaque décision prise ou rejetée est journalisée et explicable").

---

## 8. Interactions avec le reste du système

- Le **Feature Builder** (Phase 2, §4.4) est le seul module qui écrit dans `feature_values`, et référence toujours une `feature_definitions.version` existante — jamais de calcul "anonyme".
- Le **Moteur de décision** lit `feature_values` et écrit dans `decisions`.
- Le **Moteur de risque** lit `decisions` et écrit dans `risk_checks`.
- Le **Moteur d'exécution** lit les `risk_checks` validés et écrit dans `orders`/`positions`.
- Le **Journal** s'abonne passivement à tous les événements (Redis Pub/Sub, Phase 2) et les persiste dans `events_journal`, indépendamment des tables métier.
- L'**API Backend** ne fait que lire ces tables (jamais d'écriture directe hors du chemin décrit ci-dessus).

---

## 9. Arborescence complétée

```
projet-quant/
├── backend/            (Phase 2)
├── frontend/            (Phase 2)
├── infra/                (Phase 3)
├── docs/
│   ├── PHASE_4_ARCHITECTURE_DONNEES.md
│   └── data-model/
│       └── schema-conceptuel.md   # version textuelle du diagramme §4, tenue à jour
├── tests/
└── (migrations SQL réelles → Phase 6)
```

---

## 10. Auto-évaluation

**Faiblesses identifiées :**
- Le volume de `order_book_snapshots` peut être sous-estimé à ce stade tant qu'on n'a pas mesuré, en Phase 7, la fréquence réelle de snapshot nécessaire et utile pour les features de microstructure (imbalance bid/ask, etc.). *Mitigation* : la politique de rétention (§6) sera ajustée empiriquement dès les premières semaines de collecte réelle, pas figée définitivement ici.
- Le versionnement figé des `feature_definitions` et `strategies` impose une discipline stricte (ne jamais modifier une version existante, toujours en créer une nouvelle) — un oubli casserait la reproductibilité des backtests passés. *Mitigation* : contrainte technique à faire respecter au niveau du code (Phase 9/10), pas seulement documentée.

**Risques de conception :**
- Sur un VPS unique (Phase 3), même avec compression TimescaleDB, une croissance imprévue du nombre de paires suivies (au-delà de 15) ou de la fréquence de snapshot du carnet d'ordres pourrait saturer le disque plus vite que prévu. *Mitigation* : monitoring de l'espace disque dès la Phase 19, avec alerte avant saturation.

**Cohérence avec les phases précédentes :** ✅ le modèle s'appuie exactement sur PostgreSQL/TimescaleDB (Phase 2/3), respecte la contrainte de coût VPS unique (rétention limitée sur le brut, illimitée sur l'essentiel), et opérationnalise concrètement l'exigence d'explicabilité de la Phase 1.

---

## 11. Prochaine étape

Phase 5 — Infrastructure DevOps : Docker Compose détaillé, CI/CD (GitHub Actions), tests automatisés, stratégie de déploiement continue, cohérente avec le VPS Fornex retenu en Phase 3.
