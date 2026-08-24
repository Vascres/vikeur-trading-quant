# MANIFESTE — Arborescence complète et instructions de rangement

**Ce document est mis à jour après chaque phase et repartagé en entier à chaque fois.**
Il indique, pour CHAQUE fichier livré depuis le début du projet : son nom de téléchargement (tel qu'il apparaît dans le chat), son **chemin exact de destination** dans votre dépôt Git, et ce qu'il faut **personnaliser à l'intérieur** avant utilisation, s'il y a lieu.

---

## Arborescence cible finale (état actuel du projet, après Phase 20 — dernière phase de la feuille de route initiale)

```
projet-quant/  (voir arborescence complète ci-dessous ; ajouts de la Phase 20 résumés ici)
├── backend/
│   ├── api/main.py                                # MIS À JOUR (Phase 20) - CORS restreint
│   ├── data_collector/adapters/htx.py              # MIS À JOUR (Phase 20) - get_order_status
│   ├── execution_engine/modes/real.py              # MIS À JOUR (Phase 20) - confirmation de remplissage
│   └── tests/
│       ├── test_real_execution_fill.py             # NOUVEAU
│       └── test_htx_adapter.py                     # MIS À JOUR
├── infra/
│   ├── hardening/
│   │   ├── setup_hardening.sh                      # NOUVEAU
│   │   └── test_kill_switch_persistence.sh         # NOUVEAU
│   └── backup/
│       └── test_restore.sh                         # NOUVEAU
└── docs/
    └── PHASE_20_PRODUCTION.md                      # NOUVEAU
```

```
projet-quant/
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── build-and-push.yml
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── importlinter.ini
│   ├── main.py                          # NOUVEAU (Phase 18) - point d'entrée du moteur
│   ├── api/
│   │   └── main.py                      # NOUVEAU Phase 18, MIS À JOUR Phase 20 (CORS restreint)
│   ├── data_collector/
│   │   ├── main.py
│   │   └── adapters/
│   │       └── htx.py
│   ├── data_normalizer/
│   │   └── main.py
│   ├── feature_engine/
│   │   ├── main.py
│   │   ├── registry.py
│   │   └── features/
│   │       ├── spread.py
│   │       ├── order_flow_imbalance.py
│   │       ├── volatility.py
│   │       ├── vwap.py
│   │       └── momentum.py
│   ├── strategies/
│   │   ├── registry.py
│   │   └── momentum_imbalance_threshold.py
│   ├── decision_engine/
│   │   ├── main.py
│   │   └── thresholds.py
│   ├── risk_engine/
│   │   ├── main.py
│   │   └── rules/
│   │       ├── kill_switch.py
│   │       ├── position_sizing.py
│   │       ├── max_exposure.py
│   │       ├── daily_loss_limit.py
│   │       ├── max_consecutive_loss.py
│   │       ├── liquidity_slippage_fees.py
│   │       └── spot_no_shorting.py
│   ├── execution_engine/
│   │   ├── main.py
│   │   ├── common.py
│   │   ├── factory.py
│   │   ├── reconciliation.py
│   │   ├── positions.py
│   │   └── modes/
│   │       ├── backtest.py
│   │       ├── paper.py
│   │       └── real.py
│   ├── backtesting/
│   │   ├── metrics.py
│   │   ├── portfolio.py
│   │   └── engine.py
│   ├── paper_trading/
│   │   └── comparison.py
│   ├── ml_engine/
│   │   ├── label_builder.py
│   │   ├── comparison.py
│   │   ├── training_pipeline.py
│   │   └── models/
│   │       ├── gradient_boosting.py
│   │       └── random_forest.py
│   ├── optimization/
│   │   ├── performance_evaluator.py
│   │   ├── capital_allocator.py
│   │   └── orchestrator.py
│   ├── monitoring/                      # NOUVEAU (Phase 19)
│   │   ├── health_checks.py
│   │   ├── alerting.py
│   │   └── main.py
│   ├── migrations/
│   │   ├── env.py
│   │   └── versions/
│   │       ├── 0001_initial_schema.py
│   │       ├── 0002_add_strategy_logic_hash.py
│   │       ├── 0003_add_decision_side.py
│   │       ├── 0004_add_backtest_trades.py
│   │       ├── 0005_add_ml_models.py
│   │       ├── 0006_add_position_decision_id.py
│   │       └── 0007_add_strategy_allocations.py
│   ├── shared/
│   │   ├── exchange_adapter.py
│   │   ├── symbol_mapping.py
│   │   ├── feature.py
│   │   ├── strategy.py
│   │   ├── execution_mode.py
│   │   ├── risk_rule.py
│   │   └── ml_model.py
│   └── tests/
│       ├── test_htx_adapter.py
│       ├── test_migrations.py
│       ├── test_normalizer.py
│       ├── test_features.py
│       ├── test_strategies.py
│       ├── test_decision_engine.py
│       ├── test_execution_engine.py
│       ├── test_risk_engine.py
│       ├── test_backtest_metrics.py
│       ├── test_backtest_portfolio.py
│       ├── test_spot_no_shorting.py
│       ├── test_positions.py
│       ├── test_comparison.py
│       ├── test_label_builder.py
│       ├── test_ml_models.py
│       ├── test_ml_comparison.py
│       ├── test_optimization.py
│       ├── test_api.py                  # NOUVEAU (Phase 18)
│       └── test_monitoring.py            # NOUVEAU (Phase 19)
├── frontend/
│   ├── Dockerfile
│   ├── package.json                     # NOUVEAU (Phase 18)
│   ├── next.config.js                   # NOUVEAU
│   ├── tailwind.config.js               # NOUVEAU
│   ├── postcss.config.js                # NOUVEAU
│   ├── tsconfig.json                    # NOUVEAU
│   ├── app/
│   │   ├── globals.css                  # NOUVEAU
│   │   ├── layout.tsx                   # NOUVEAU
│   │   └── page.tsx                     # NOUVEAU
│   ├── components/
│   │   ├── KillSwitchButton.tsx         # NOUVEAU
│   │   ├── TradingViewChart.tsx         # NOUVEAU
│   │   ├── PositionsTable.tsx           # NOUVEAU
│   │   ├── DecisionsTable.tsx           # NOUVEAU
│   │   ├── LogsList.tsx                 # NOUVEAU
│   │   └── StrategyPerformanceTable.tsx # NOUVEAU
│   └── lib/
│       └── api.ts                       # NOUVEAU
├── infra/
│   ├── docker-compose.yml               # MIS À JOUR (Phase 18 : service "engine" ; Phase 19 : service "monitoring")
│   ├── Caddyfile
│   ├── .env.example
│   └── deploy.sh
└── docs/
    ├── PHASE_1_VISION_PRODUIT.md
    ├── PHASE_2_ARCHITECTURE_LOGICIELLE.md
    ├── PHASE_3_ARCHITECTURE_CLOUD.md
    ├── PHASE_4_ARCHITECTURE_DONNEES.md
    ├── PHASE_5_INFRASTRUCTURE_DEVOPS.md
    ├── PHASE_6_BASE_DE_DONNEES.md
    ├── PHASE_7_COLLECTE_DONNEES.md
    ├── PHASE_8_NORMALISATION.md
    ├── PHASE_9_FEATURES.md
    ├── PHASE_10_FRAMEWORK_STRATEGIES.md
    ├── PHASE_11_MOTEUR_DECISION.md
    ├── PHASE_12_MOTEUR_EXECUTION.md
    ├── PHASE_13_GESTION_RISQUES.md
    ├── PHASE_14_BACKTESTING.md
    ├── PHASE_15_PAPER_TRADING.md
    ├── PHASE_16_MACHINE_LEARNING.md
    ├── PHASE_17_OPTIMISATION.md
    ├── PHASE_18_DASHBOARD.md
    ├── PHASE_19_MONITORING.md
    └── PHASE_20_PRODUCTION.md
```

**Note importante sur les noms de téléchargement** : quand deux fichiers réels portent le même nom (ex. `backend/Dockerfile` et `frontend/Dockerfile`, ou `data_collector/main.py` et `data_normalizer/main.py`), l'outil de partage du chat ne peut pas proposer deux téléchargements identiques nommés pareil — je les renomme donc temporairement (ex. `backend.Dockerfile`, `data_normalizer_main.py`) **uniquement pour le téléchargement**. Le tableau ci-dessous précise à chaque fois le nom réel attendu dans le dépôt.

---

## Tableau détaillé — tous les fichiers livrés à ce jour

| Nom de téléchargement (chat) | Chemin réel dans le dépôt | À personnaliser à l'intérieur ? |
|---|---|---|
| PHASE 1 VISION PRODUIT | `docs/PHASE_1_VISION_PRODUIT.md` | Non — document de référence, ne pas modifier son contenu (sert de socle aux phases suivantes) |
| PHASE 2 ARCHITECTURE LOGICIELLE | `docs/PHASE_2_ARCHITECTURE_LOGICIELLE.md` | Non |
| PHASE 3 ARCHITECTURE CLOUD | `docs/PHASE_3_ARCHITECTURE_CLOUD.md` | Non |
| PHASE 4 ARCHITECTURE DONNEES | `docs/PHASE_4_ARCHITECTURE_DONNEES.md` | Non |
| PHASE 5 INFRASTRUCTURE DEVOPS | `docs/PHASE_5_INFRASTRUCTURE_DEVOPS.md` | Non |
| PHASE 6 BASE DE DONNEES | `docs/PHASE_6_BASE_DE_DONNEES.md` | Non |
| PHASE 7 COLLECTE DONNEES | `docs/PHASE_7_COLLECTE_DONNEES.md` | Non |
| PHASE 8 NORMALISATION | `docs/PHASE_8_NORMALISATION.md` | Non |
| PHASE 9 FEATURES | `docs/PHASE_9_FEATURES.md` | Non |
| PHASE 10 FRAMEWORK STRATEGIES | `docs/PHASE_10_FRAMEWORK_STRATEGIES.md` | Non |
| PHASE 11 MOTEUR DECISION | `docs/PHASE_11_MOTEUR_DECISION.md` | Non |
| PHASE 12 MOTEUR EXECUTION | `docs/PHASE_12_MOTEUR_EXECUTION.md` | Non |
| PHASE 13 GESTION RISQUES | `docs/PHASE_13_GESTION_RISQUES.md` | Non |
| PHASE 14 BACKTESTING | `docs/PHASE_14_BACKTESTING.md` | Non |
| PHASE 15 PAPER TRADING | `docs/PHASE_15_PAPER_TRADING.md` | Non |
| PHASE 16 MACHINE LEARNING | `docs/PHASE_16_MACHINE_LEARNING.md` | Non |
| PHASE 17 OPTIMISATION | `docs/PHASE_17_OPTIMISATION.md` | Non |
| PHASE 18 DASHBOARD | `docs/PHASE_18_DASHBOARD.md` | Non |
| PHASE 19 MONITORING | `docs/PHASE_19_MONITORING.md` | Non |
| PHASE 20 PRODUCTION | `docs/PHASE_20_PRODUCTION.md` | Non |
| api main (mis à jour Phase 20, téléchargé sous "api_main_v2") | `backend/api/main.py` **(remplace la version de la Phase 18, CORS restreint)** | Non |
| htx (mis à jour Phase 20, téléchargé sous "htx_v2") | `backend/data_collector/adapters/htx.py` **(remplace la version de la Phase 12, ajoute get_order_status)** | Non |
| execution real (mis à jour Phase 20, téléchargé sous "real_v3") | `backend/execution_engine/modes/real.py` **(remplace la version de la Phase 17)** | Non |
| test real execution fill | `backend/tests/test_real_execution_fill.py` | Non |
| test htx adapter (mis à jour Phase 20) | `backend/tests/test_htx_adapter.py` **(remplace la version de la Phase 12)** | Non |
| setup hardening | `infra/hardening/setup_hardening.sh` | À exécuter manuellement une fois sur le VPS (§4 du document de phase) |
| test kill switch persistence | `infra/hardening/test_kill_switch_persistence.sh` | Non |
| test restore | `infra/backup/test_restore.sh` | Non |
| monitoring health checks | `backend/monitoring/health_checks.py` | Seuils dans `main.py` à calibrer |
| monitoring alerting | `backend/monitoring/alerting.py` | Non |
| monitoring main (téléchargé sous "monitoring_main") | `backend/monitoring/main.py` | `MODULE_FRESHNESS_THRESHOLDS`, `MAX_RECONNECTIONS_PER_WINDOW` à calibrer |
| docker-compose (mis à jour Phase 19) | `infra/docker-compose.yml` **(remplace la version de la Phase 18, ajoute le service "monitoring")** | Non |
| .env (mis à jour Phase 19) | `infra/.env.example` | **OUI** : `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (créer un bot via @BotFather) |
| test monitoring | `backend/tests/test_monitoring.py` | Non |
| engine main (téléchargé sous "engine_main") | `backend/main.py` | Non |
| api main (téléchargé sous "api_main") | `backend/api/main.py` | Non |
| docker-compose (mis à jour Phase 18) | `infra/docker-compose.yml` **(remplace la version de la Phase 5, ajoute le service "engine")** | Non |
| test api | `backend/tests/test_api.py` | Non |
| package.json | `frontend/package.json` | Non |
| next.config | `frontend/next.config.js` | Non |
| tailwind.config | `frontend/tailwind.config.js` | Non |
| postcss.config | `frontend/postcss.config.js` | Non |
| tsconfig | `frontend/tsconfig.json` | Non |
| globals.css | `frontend/app/globals.css` | Non |
| layout | `frontend/app/layout.tsx` | Non |
| page | `frontend/app/page.tsx` | Non |
| KillSwitchButton | `frontend/components/KillSwitchButton.tsx` | Non |
| TradingViewChart | `frontend/components/TradingViewChart.tsx` | Symbole `HTX:BTCUSDT` par défaut, ajustable |
| PositionsTable | `frontend/components/PositionsTable.tsx` | Non |
| DecisionsTable | `frontend/components/DecisionsTable.tsx` | Non |
| LogsList | `frontend/components/LogsList.tsx` | Non |
| StrategyPerformanceTable | `frontend/components/StrategyPerformanceTable.tsx` | Non |
| api (lib) | `frontend/lib/api.ts` | Non |
| 0006 add position decision id | `backend/migrations/versions/0006_add_position_decision_id.py` | Non |
| 0007 add strategy allocations | `backend/migrations/versions/0007_add_strategy_allocations.py` | Non |
| execution mode (mis à jour Phase 17) | `backend/shared/execution_mode.py` **(remplace la version de la Phase 12)** | Non |
| execution positions (mis à jour Phase 17) | `backend/execution_engine/positions.py` **(remplace la version de la Phase 15)** | Non |
| execution paper (mis à jour Phase 17, téléchargé sous "paper_v3") | `backend/execution_engine/modes/paper.py` **(remplace la version de la Phase 15)** | Non |
| execution backtest (mis à jour Phase 17, téléchargé sous "backtest_v2") | `backend/execution_engine/modes/backtest.py` **(remplace la version de la Phase 12)** | Non |
| execution real (mis à jour Phase 17, téléchargé sous "real_v2") | `backend/execution_engine/modes/real.py` **(remplace la version de la Phase 12)** | Non |
| execution engine main (mis à jour Phase 17, téléchargé sous "execution_engine_main_v2") | `backend/execution_engine/main.py` **(remplace la version de la Phase 13)** | Non |
| test execution engine (mis à jour Phase 17) | `backend/tests/test_execution_engine.py` **(remplace la version de la Phase 12)** | Non |
| test positions (mis à jour Phase 17) | `backend/tests/test_positions.py` **(remplace la version de la Phase 15, compatible sans changement de code)** | Non |
| optimization performance evaluator | `backend/optimization/performance_evaluator.py` | `MIN_TRADES_BEFORE_JUDGMENT` à calibrer |
| optimization capital allocator | `backend/optimization/capital_allocator.py` | Non |
| optimization orchestrator | `backend/optimization/orchestrator.py` | `ROLLING_WINDOW_TRADES` à calibrer |
| test optimization | `backend/tests/test_optimization.py` | Non |
| pyproject | `backend/pyproject.toml` | Non (corrige le manque bloquant le CI depuis la Phase 5) |
| 0005 add ml models | `backend/migrations/versions/0005_add_ml_models.py` | Non |
| ml model | `backend/shared/ml_model.py` | Non |
| label builder | `backend/ml_engine/label_builder.py` | `LABEL_HORIZON_PERIODS` (dans training_pipeline) ajustable |
| gradient boosting | `backend/ml_engine/models/gradient_boosting.py` | Non |
| random forest | `backend/ml_engine/models/random_forest.py` | Non |
| ml comparison (téléchargé sous "ml_comparison") | `backend/ml_engine/comparison.py` | `PREDICTION_THRESHOLD`/`ASSUMED_COST_FRACTION` ajustables |
| training pipeline | `backend/ml_engine/training_pipeline.py` | Non |
| .env (mis à jour Phase 16) | `infra/.env.example` | **OUI** : nouvelle variable `ML_ENABLED` (sans effet actuel) |
| importlinter (mis à jour Phase 16) | `backend/importlinter.ini` **(remplace la version de la Phase 10)** | Non |
| test label builder | `backend/tests/test_label_builder.py` | Non |
| test ml models | `backend/tests/test_ml_models.py` | Non |
| test ml comparison | `backend/tests/test_ml_comparison.py` | Non |
| risk rule (mis à jour Phase 15) | `backend/shared/risk_rule.py` **(remplace la version de la Phase 13)** | Non |
| spot no shorting | `backend/risk_engine/rules/spot_no_shorting.py` | Non |
| risk engine main (mis à jour Phase 15, téléchargé sous "risk_engine_main_v2") | `backend/risk_engine/main.py` **(remplace la version de la Phase 13)** | Non |
| execution positions | `backend/execution_engine/positions.py` | Non |
| execution paper (mis à jour Phase 15, téléchargé sous "paper_v2") | `backend/execution_engine/modes/paper.py` **(remplace la version de la Phase 12)** | Non |
| paper trading comparison | `backend/paper_trading/comparison.py` | Non |
| test spot no shorting | `backend/tests/test_spot_no_shorting.py` | Non |
| test positions | `backend/tests/test_positions.py` | Non |
| test comparison | `backend/tests/test_comparison.py` | Non |
| 0004 add backtest trades | `backend/migrations/versions/0004_add_backtest_trades.py` | Non |
| backtest metrics | `backend/backtesting/metrics.py` | Non |
| backtest portfolio | `backend/backtesting/portfolio.py` | Non |
| backtest engine | `backend/backtesting/engine.py` | Non |
| test backtest metrics | `backend/tests/test_backtest_metrics.py` | Non |
| test backtest portfolio | `backend/tests/test_backtest_portfolio.py` | Non |
| .env (mis à jour) | `infra/.env.example` | **OUI** : nouvelle variable `STARTING_CAPITAL` à définir selon votre capital réel (Phase 1 : <10k$) |
| 0003 add decision side | `backend/migrations/versions/0003_add_decision_side.py` | Non |
| decision engine main (mis à jour Phase 13, téléchargé sous "decision_engine_main_v2") | `backend/decision_engine/main.py` **(remplace la version de la Phase 11)** | Non |
| risk rule | `backend/shared/risk_rule.py` | Non |
| kill switch | `backend/risk_engine/rules/kill_switch.py` | Non |
| position sizing | `backend/risk_engine/rules/position_sizing.py` | `MAX_RISK_FRACTION`/`KELLY_DIVISOR` à calibrer en Phase 14 |
| max exposure | `backend/risk_engine/rules/max_exposure.py` | `MAX_EXPOSURE_FRACTION` à calibrer en Phase 14 |
| daily loss limit | `backend/risk_engine/rules/daily_loss_limit.py` | `MAX_DAILY_LOSS_FRACTION` à calibrer en Phase 14 |
| max consecutive loss | `backend/risk_engine/rules/max_consecutive_loss.py` | `MAX_CONSECUTIVE_LOSSES` à calibrer en Phase 14 |
| liquidity slippage fees | `backend/risk_engine/rules/liquidity_slippage_fees.py` | `MAX_SLIPPAGE_BPS`/`ASSUMED_ROUND_TRIP_FEE_BPS` à calibrer en Phase 14 |
| risk engine main (téléchargé sous "risk_engine_main") | `backend/risk_engine/main.py` | Non |
| execution engine main (Phase 13, téléchargé sous "execution_engine_main") | `backend/execution_engine/main.py` | Non |
| test risk engine | `backend/tests/test_risk_engine.py` | Non |
| docker-compose | `infra/docker-compose.yml` | Non directement — toutes les valeurs viennent de `.env` (voir ligne suivante) |
| Caddyfile | `infra/Caddyfile` | Non directement — utilise la variable `DOMAIN_NAME` définie dans `.env` |
| .env (téléchargé depuis `.env.example`) | `infra/.env.example` **→ à copier en `infra/.env` sur le VPS uniquement, jamais dans Git** | **OUI, impératif.** Remplacer : `IMAGE_REGISTRY` (votre utilisateur GitHub), `DOMAIN_NAME` et `PUBLIC_API_URL` (votre nom de domaine réel), `POSTGRES_PASSWORD`, `REDIS_PASSWORD` (mots de passe forts), `EXCHANGE_API_KEY`/`EXCHANGE_API_SECRET` (à partir de la Phase 12), `BACKUP_STORAGE_*` (vos identifiants de stockage objet) |
| deploy | `infra/deploy.sh` | Non dans le fichier — mais nécessite deux variables d'environnement **sur votre machine locale** au moment de l'exécuter : `VPS_HOST` (ex. `root@ip_de_votre_vps_fornex`) et éventuellement `REMOTE_DIR` si différent de `/opt/projet-quant` |
| backend (Dockerfile) | `backend/Dockerfile` | Non |
| frontend (Dockerfile) | `frontend/Dockerfile` | Non |
| ci | `.github/workflows/ci.yml` | Non |
| build-and-push | `.github/workflows/build-and-push.yml` | Non |
| importlinter | `backend/importlinter.ini` | Non |
| alembic | `backend/alembic.ini` | Non |
| env (Alembic) | `backend/migrations/env.py` | Non |
| 0001 initial schema | `backend/migrations/versions/0001_initial_schema.py` | Non |
| test migrations | `backend/tests/test_migrations.py` | Non |
| exchange adapter | `backend/shared/exchange_adapter.py` | Non |
| htx | `backend/data_collector/adapters/htx.py` | Non |
| main (collecteur, Phase 7) | `backend/data_collector/main.py` | Optionnel : variable d'environnement `TRACKED_SYMBOLS` si vous voulez suivre d'autres paires que BTC/ETH/SOL par défaut |
| test htx adapter | `backend/tests/test_htx_adapter.py` | Non |
| symbol mapping | `backend/shared/symbol_mapping.py` | **OUI si vous ajoutez une paire** : ajouter l'entrée dans `HTX_NATIVE_TO_CANONICAL` |
| data normalizer main (Phase 8) | `backend/data_normalizer/main.py` | Non |
| test normalizer | `backend/tests/test_normalizer.py` | Non |
| feature | `backend/shared/feature.py` | Non |
| spread | `backend/feature_engine/features/spread.py` | Non |
| order flow imbalance | `backend/feature_engine/features/order_flow_imbalance.py` | Non |
| volatility | `backend/feature_engine/features/volatility.py` | Non |
| vwap | `backend/feature_engine/features/vwap.py` | Non |
| momentum | `backend/feature_engine/features/momentum.py` | Non |
| registry | `backend/feature_engine/registry.py` | **OUI si vous ajoutez une feature** : l'ajouter à la liste `ACTIVE_FEATURES` |
| feature engine main (Phase 9) | `backend/feature_engine/main.py` | Non |
| test features | `backend/tests/test_features.py` | Non |
| 0002 add strategy logic hash | `backend/migrations/versions/0002_add_strategy_logic_hash.py` | Non |
| strategy | `backend/shared/strategy.py` | Non |
| momentum imbalance threshold | `backend/strategies/momentum_imbalance_threshold.py` | Paramètres ajustables via `DEFAULT_PARAMETERS` (seuils), sans changer la version tant que la logique de `evaluate()` reste identique |
| strategies registry (téléchargé sous "strategies_registry") | `backend/strategies/registry.py` | **OUI si vous ajoutez une stratégie** : l'ajouter à `ACTIVE_STRATEGIES` |
| test strategies | `backend/tests/test_strategies.py` | Non |
| decision thresholds | `backend/decision_engine/thresholds.py` | **OUI si vous voulez ajuster les seuils** avant calibrage empirique (Phase 14) : `DECISION_THRESHOLDS`, `FEATURE_FRESHNESS_SECONDS` |
| decision engine main (téléchargé sous "decision_engine_main") | `backend/decision_engine/main.py` | Non |
| test decision engine | `backend/tests/test_decision_engine.py` | Non |
| htx (mis à jour en Phase 12) | `backend/data_collector/adapters/htx.py` **(remplace la version de la Phase 7)** | Non dans le fichier — mais nécessite `EXCHANGE_API_KEY`/`EXCHANGE_API_SECRET` renseignés dans `.env` pour utiliser le mode réel |
| execution mode | `backend/shared/execution_mode.py` | Non |
| execution engine common | `backend/execution_engine/common.py` | Non |
| execution backtest | `backend/execution_engine/modes/backtest.py` | Seuils `ASSUMED_SLIPPAGE_BPS`/`ASSUMED_FEE_BPS` à calibrer en Phase 14 |
| execution paper | `backend/execution_engine/modes/paper.py` | Idem |
| execution real | `backend/execution_engine/modes/real.py` | Non |
| execution factory | `backend/execution_engine/factory.py` | Non |
| execution reconciliation | `backend/execution_engine/reconciliation.py` | Non |
| test execution engine | `backend/tests/test_execution_engine.py` | Non |

---

## Fichiers non encore livrés mais déjà référencés dans les documents

Aucun à ce stade — tout ce qui a été mentionné dans les documents de décisions a été livré.

---

## Règle appliquée à partir de maintenant

À chaque phase suivante, je vous donnerai systématiquement :
1. La liste des nouveaux fichiers avec leur chemin exact.
2. Ce document MANIFESTE mis à jour dans son intégralité (pas seulement les nouveautés), pour que vous ayez toujours une vue complète et à jour en un seul endroit.
