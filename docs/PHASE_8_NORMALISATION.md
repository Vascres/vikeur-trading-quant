# Phase 8 — Normalisation des données
## Plateforme quantitative de trading crypto — V1

**Statut : Phase 8 en cours de validation.**
**Prérequis : Phases 1 à 7 validées.** Marché confirmé : **Spot**, exchange HTX.

---

## 1. Besoin métier de cette phase

Le collecteur (Phase 7) transmet des messages HTX quasi bruts. Pour que le Feature Builder (Phase 9) et tout le reste du pipeline puissent fonctionner **indépendamment de l'exchange**, il faut un point unique de conversion vers un format canonique — c'est tout l'enjeu de cette phase, et la clé de l'objectif d'extensibilité de la Phase 1 (ajouter un 2e exchange sans toucher au Feature Builder).

## 2. Problème technique

Convertir les messages HTX (symboles en minuscules concaténés type `btcusdt`, horodatage en millisecondes epoch, champ `direction` pour le sens) vers le schéma canonique défini en Phase 4/6 (`BTC/USDT`, `TIMESTAMPTZ`, `side` normalisé), tout en détectant les trous de données (déconnexion non signalée, message manquant) avant qu'ils ne faussent silencieusement un backtest ou une décision.

---

## 3. Décisions de conception

### 3.1 Mapping de symboles
Un mapping explicite par exchange (`shared/symbol_mapping.py`), pas de déduction automatique par regex — une déduction automatique serait plus "magique" mais casserait silencieusement sur un symbole inattendu (ex. `USDT` vs `USD`, paires avec plus de 2 segments). Un mapping explicite échoue bruyamment (erreur claire) sur un symbole non prévu, ce qui est préférable pour un système qui gère du capital réel.

### 3.2 Détection de trous (gap detection)
Le Normalizer garde en mémoire, par paire, le timestamp du dernier trade traité. Si l'écart dépasse un seuil configurable (60 secondes par défaut en V1 — à ajuster empiriquement), un événement `data.gap_detected` est publié vers le Journal. **Ce n'est pas bloquant en soi** (le Moteur de risque, Phase 2 §4.6, est le niveau qui décidera si un signal doit être ignoré faute de données fraîches — pas le Normalizer, qui reste un module de transformation, pas de décision).

### 3.3 Dé-duplication
HTX recommande explicitement d'utiliser `tradeId` pour dédupliquer (confirmé dans la documentation officielle). Le Normalizer garde un petit cache des derniers `trade_id` traités par paire pour ignorer les doublons en cas de reconnexion avec chevauchement (backfill REST + flux WebSocket qui se recoupent).

### 3.4 Écriture en base
Écriture par lots (micro-batch, ex. toutes les 500ms ou tous les 100 messages) plutôt qu'une insertion par message — réduit la charge sur TimescaleDB, cohérent avec la contrainte de VPS unique (Phase 3).

---

## 4. Fichiers produits dans cette phase

- `backend/shared/symbol_mapping.py` — mapping canonique par exchange.
- `backend/data_normalizer/main.py` — service de normalisation (Redis → TimescaleDB).
- `backend/tests/test_normalizer.py` — tests de parsing, mapping, détection de trous, dé-duplication.

---

## 5. Interactions avec le reste du système

- Consomme les canaux Redis `raw:htx:trade` et `raw:htx:depth` publiés par le collecteur (Phase 7) — **aucun import Python entre les deux modules**, uniquement un couplage par message (cohérent avec le choix Redis Pub/Sub de la Phase 2, §2).
- Écrit dans `raw_market_data` et `order_book_snapshots` (Phase 6).
- Publie les événements de gap/erreur vers le canal du Journal (Phase 4 §5.5), au même titre que le collecteur.

---

## 6. Auto-évaluation

**Faiblesses identifiées :**
- Le seuil de 60 secondes pour la détection de trou est une valeur de départ raisonnable mais arbitraire — à recalibrer avec des données réelles dès les premiers jours de fonctionnement.
- Le cache de dé-duplication des `trade_id` est en mémoire (perdu au redémarrage) — un doublon reste possible dans la fenêtre exacte d'un redémarrage. Impact jugé négligeable en V1 (un doublon de trade fausse marginalement un volume agrégé, sans risque sur les décisions elles-mêmes qui s'appuient sur des candles agrégées).

**Cohérence avec les phases précédentes :** ✅ le mapping canonique prépare directement l'ajout d'un 2e exchange (Phase 1) ; l'écriture respecte exactement le schéma de la Phase 6.

---

## 7. Prochaine étape

Phase 9 — Construction des features : premières features versionnées (spread, volatilité, order flow) calculées à partir de `raw_market_data`/`ohlcv_candles`.
