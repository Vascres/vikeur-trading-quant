"""Registre des features (Phase 9, §3).

Au démarrage, vérifie pour chaque feature active que son code source
correspond exactement au hash enregistré pour sa version dans
feature_definitions (Phase 6). Refuse de démarrer sinon - c'est la
contrainte technique qui rend le versionnement réellement infalsifiable,
et non plus seulement documenté (mitigation de l'auto-évaluation, Phase 4).
"""

from __future__ import annotations

import hashlib
import inspect

import asyncpg

from feature_engine.features.liquidation_cascade_intensity import LiquidationCascadeIntensity
from feature_engine.features.momentum import Momentum
from feature_engine.features.order_flow_imbalance import OrderFlowImbalance
from feature_engine.features.spread import SpreadBps
from feature_engine.features.volatility import RealizedVolatility
from feature_engine.features.vwap import Vwap
from shared.feature import Feature

# Features actives en V1 (Phase 9, §4). Ajouter une feature = ajouter une
# entrée ici après l'avoir écrite dans feature_engine/features/.
ACTIVE_FEATURES: list[Feature] = [
    SpreadBps(),
    OrderFlowImbalance(),
    RealizedVolatility(),
    Vwap(),
    Momentum(),
    # Chantier Liquidation Cascade (16/08/2026) - donnée disponible
    # uniquement pour les exchanges où `liquidation_ingest` tourne
    # (Binance à ce jour) ; retourne 0.0 ailleurs (fenêtre vide, jamais
    # None - cf. docstring de la feature), jamais bloquant pour les
    # autres features de ce même cycle.
    LiquidationCascadeIntensity(),
]


class FeatureVersionConflictError(RuntimeError):
    """Levée quand le code d'une feature a changé sans que sa version ait été incrémentée."""


def compute_logic_hash(feature: Feature) -> str:
    source = inspect.getsource(feature.compute)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


async def register_and_verify_features(db_pool: asyncpg.Pool) -> dict[str, int]:
    """Retourne {feature_name: feature_definition_id} pour les features actives.

    Lève FeatureVersionConflictError si une version existante a un hash
    différent de celui du code actuel (Phase 9, §3).
    """
    feature_definition_ids: dict[str, int] = {}

    async with db_pool.acquire() as conn:
        for feature in ACTIVE_FEATURES:
            name = feature.metadata.name
            version = feature.metadata.version
            current_hash = compute_logic_hash(feature)

            existing = await conn.fetchrow(
                "SELECT id, logic_hash FROM feature_definitions WHERE name = $1 AND version = $2",
                name,
                version,
            )

            if existing is None:
                new_id = await conn.fetchval(
                    """
                    INSERT INTO feature_definitions (name, version, description, logic_hash)
                    VALUES ($1, $2, $3, $4)
                    RETURNING id;
                    """,
                    name,
                    version,
                    feature.metadata.description,
                    current_hash,
                )
                feature_definition_ids[name] = new_id

            elif existing["logic_hash"] != current_hash:
                raise FeatureVersionConflictError(
                    f"La feature '{name}' version {version} a été modifiée dans le code "
                    f"(hash attendu {existing['logic_hash']}, obtenu {current_hash}). "
                    "Le versionnement figé (Phase 4 §5.2, Phase 9 §3) interdit de modifier "
                    "une version existante : incrémentez `version` dans la classe de la feature."
                )
            else:
                feature_definition_ids[name] = existing["id"]

    return feature_definition_ids
