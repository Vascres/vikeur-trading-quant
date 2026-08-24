# Phase 14 — Backtesting
## Plateforme quantitative de trading crypto — V1

**Statut : Phase 14 en cours de validation.**
**Prérequis : Phases 1 à 13 validées.**

---

## 1. Besoin métier de cette phase

C'est le moment de vérité prévu depuis la Phase 1 : **aucune stratégie ne passe en paper trading (Phase 15) ni en réel sans avoir été validée ici**, sur un historique suffisant, avec des métriques rigoureuses et non complaisantes.

## 2. Problème technique

Rejouer l'historique à travers **la même logique** que le temps réel (stratégies, seuils de décision, règles de risque — critère non négociable de la Phase 1/2), sans pour autant polluer les tables live (`decisions`, `risk_checks`, `orders`, `positions`) avec des milliers de lignes simulées à chaque run de backtest, et sans exiger une donnée (carnet d'ordres historique) que la politique de rétention de la Phase 4 ne conserve que 30 jours.

---

## 3. Décisions de conception

### 3.1 Isolation des données de backtest

**Contrairement au trading réel/paper**, le backtest ne persiste pas chaque décision/vérification de risque/ordre simulé dans les tables live (Phase 6) — un run de backtest peut rejouer plusieurs années de données et générer des milliers d'évaluations ; les écrire dans `decisions`/`risk_checks`/`orders` pollueraient ces tables (conçues pour l'explicabilité d'un flux réel, pas pour des simulations répétées) et nécessiteraient une chaîne de migrations supplémentaire (`backtest_run_id` sur 4 tables).

**Décision retenue** : une nouvelle table dédiée `backtest_trades` (migration `0004`) enregistre chaque position simulée (entrée, sortie, PnL), reliée à `backtest_runs`. Les tables `decisions`/`risk_checks`/`orders`/`positions` restent exclusivement pour le flux réel/paper (Phase 13/15).

### 3.2 Réutilisation réelle de la logique de décision et de risque

Ce qui est **réellement réutilisé sans aucune duplication** :
- `Strategy.evaluate()` (Phase 10) — le même code, appelé avec des features historiques au lieu de features "actuelles".
- `evaluate_verdict()` (Phase 11) — les mêmes seuils.
- Les règles `PositionSizingRule`, `MaxExposureRule`, `DailyLossLimitRule`, `MaxConsecutiveLossRule` (Phase 13) — les mêmes classes, appelées avec un `RiskContext` construit à partir de l'état simulé du backtest plutôt que de l'état live.

**Simplification assumée** : `LiquiditySlippageFeesRule` (Phase 13) nécessite un carnet d'ordres réel, or la Phase 4 ne conserve l'historique du carnet que 30 jours — incompatible avec un backtest pluriannuel. Pour le backtest, le coût d'exécution utilise le **modèle fixe déjà présent dans `BacktestExecutionMode`** (Phase 12 : slippage + frais en points de base assumés), plutôt que de simuler un carnet historique inexistant. C'est une limitation honnête, pas un contournement caché — documentée ici et dans l'auto-évaluation.

### 3.3 Fenêtre de rejeu

Le moteur avance candle par candle (`ohlcv_candles_1m`, Phase 6) sur la période demandée, assemble à chaque pas les dernières valeurs de chaque feature **antérieures ou égales** à l'instant simulé (jamais une donnée du futur — condition stricte pour un backtest valide), puis applique exactement la chaîne Stratégie → Seuils → Règles de risque → Exécution (mode backtest).

---

## 4. Métriques calculées (Phase 6, `backtest_results`)

Sharpe, Sortino, Calmar, Max Drawdown, Profit Factor, Expectancy, Ulcer Index — chacune implémentée comme une **fonction pure** à partir de la liste des PnL de trades et de la courbe d'équité, testable sans base de données.

---

## 5. Fichiers produits dans cette phase

- `backend/migrations/versions/0004_add_backtest_trades.py` — nouvelle table `backtest_trades`.
- `backend/backtesting/metrics.py` — fonctions pures des 7 métriques.
- `backend/backtesting/portfolio.py` — logique pure d'ouverture/fermeture de position simulée (testable sans DB).
- `backend/backtesting/engine.py` — orchestration du rejeu historique.
- `backend/tests/test_backtest_metrics.py`, `test_backtest_portfolio.py` — tests des fonctions pures.

---

## 6. Ce que cette phase ne couvre pas encore (limitations honnêtes)

- **Monte Carlo, Walk Forward Analysis, stress tests, rapport PDF automatique** (mentionnés dans le brief initial) : différés. Le socle (rejeu fidèle + métriques correctes) doit être validé en premier — ajouter une couche Monte Carlo sur un moteur non encore éprouvé donnerait une fausse impression de rigueur. Ce sont des candidats naturels pour un enrichissement ultérieur de cette même phase, une fois le socle validé avec vos propres runs.
- **Tick data réel** : le backtest utilise les candles 1 minute (`ohlcv_candles_1m`), pas le tick-by-tick brut. Cohérent avec l'horizon de décision minute/heure de la Phase 1 — le tick-by-tick n'apporterait pas de précision utile à ce niveau et son historique est de toute façon purgé après 90 jours (Phase 4, §6).
- **Le suivi continu des positions dans les tables live (`positions`)** n'est, à ce stade du projet, jamais réellement peuplé même en paper/réel (les modes d'exécution de la Phase 12 écrivent des `orders` mais pas encore de `positions`). Ce n'est pas bloquant pour le backtest (qui gère son propre état simulé en mémoire, §3.1), mais **c'est un point à traiter explicitement dès la Phase 15** puisque le paper trading a précisément besoin de ce suivi pour être comparable au réel.

---

## 7. Auto-évaluation

**Faiblesses identifiées :** voir §6 - limitations assumées et priorisées plutôt que cachées.

**Cohérence avec les phases précédentes :** ✅ réutilise réellement le code de décision (Phase 10/11) et de risque (Phase 13) sans duplication, à l'exception documentée de la règle de liquidité (§3.2).

---

## 8. Prochaine étape

Phase 15 — Paper Trading : activer le suivi réel des positions dans les tables live (`positions`), condition pour comparer objectivement paper trading et trading réel (Phase 1).
