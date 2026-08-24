"""Registre des moteurs de décision (Phase 10, §4 ; ADR-0010).

Miroir exact de feature_engine/registry.py (Phase 9, §3) : même mécanisme
de hash SHA-256 du code source, appliqué ici à `strategies.logic_hash`
(colonne ajoutée par la migration 0002 - Phase 10, §4). Le nom de la
table (`strategies`) et de ce module sont conservés tels quels (ADR-0010
- un renommage en `decision_engines` serait un pur nettoyage cosmétique,
sans risque, mais volontairement différé pour ne pas élargir le
périmètre de ce chantier).
"""

from __future__ import annotations

import hashlib
import inspect
import json

import asyncpg

from shared.decision_engine import DecisionEngine
from strategies.cross_sectional_momentum import CrossSectionalMomentum
from strategies.liquidation_cascade import LiquidationCascadeAgent
from strategies.momentum_imbalance_threshold import MomentumImbalanceThreshold
from strategies.order_book_imbalance import OrderBookImbalance

# Moteurs actifs (ADR-0010, chantier 4 : 2 moteurs pour prouver le motif
# de fusion avant d'en ajouter d'autres - ADR-0006). Ajouter un moteur =
# l'ajouter ici après l'avoir écrit dans strategies/.
# ADR-0017 : cross_sectional_momentum est la première famille de signal
# réellement différente des deux premières (série temporelle) - cf.
# CONCEPTION_AGENT_CROSS_SECTIONAL.md pour la justification complète.
#
# Chantier Liquidation Cascade (16/08/2026) : liquidation_cascade est le
# premier moteur `market_type="futures_perpetual"` (EngineMetadata) -
# `decision_engine/main.py` le fusionne séparément des 3 moteurs spot
# ci-dessus, jamais dans la même décision. Démarre en EXPERIMENTAL
# (Strategy Lifecycle, Étape 3) dès son premier enregistrement - paper
# uniquement, aucune donnée de calibration réelle n'existe encore.
ACTIVE_STRATEGIES: list[DecisionEngine] = [
    MomentumImbalanceThreshold(),
    OrderBookImbalance(),
    CrossSectionalMomentum(),
    LiquidationCascadeAgent(),
]


class StrategyVersionConflictError(RuntimeError):
    """Levée quand le code d'un moteur a changé sans que sa version ait été incrémentée."""


def compute_logic_hash(strategy: DecisionEngine) -> str:
    source = inspect.getsource(strategy.evaluate)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


async def register_and_verify_strategies(db_pool: asyncpg.Pool) -> dict[str, int]:
    """Retourne {strategy_name: strategy_id} pour les moteurs actifs.

    Lève StrategyVersionConflictError si une version existante a un hash
    différent de celui du code actuel (Phase 10, §4).
    """
    strategy_ids: dict[str, int] = {}

    async with db_pool.acquire() as conn:
        for strategy in ACTIVE_STRATEGIES:
            name = strategy.metadata.name
            version = strategy.metadata.version
            current_hash = compute_logic_hash(strategy)

            existing = await conn.fetchrow(
                "SELECT id, logic_hash FROM strategies WHERE name = $1 AND version = $2",
                name,
                version,
            )

            if existing is None:
                new_id = await conn.fetchval(
                    """
                    INSERT INTO strategies (name, version, parameters, is_active, logic_hash)
                    VALUES ($1, $2, $3, true, $4)
                    RETURNING id;
                    """,
                    name,
                    version,
                    json.dumps(getattr(strategy, "parameters", {})),
                    current_hash,
                )
                strategy_ids[name] = new_id

            elif existing["logic_hash"] != current_hash:
                raise StrategyVersionConflictError(
                    f"Le moteur '{name}' version {version} a été modifié dans le code "
                    f"(hash attendu {existing['logic_hash']}, obtenu {current_hash}). "
                    "Incrémentez `version` dans la classe du moteur plutôt que de "
                    "modifier une version existante (Phase 4 §5.3, Phase 10 §4)."
                )
            else:
                strategy_ids[name] = existing["id"]

    return strategy_ids
