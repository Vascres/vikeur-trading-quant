"""Service decision_engine (Phase 11 ; ADR-0010 ; ADR-0014 ; ADR-0015).

Autorisé à importer feature_engine, strategies, et meta_engine (couches
Phase 2/10 ; meta_engine est une couche de fusion, pas d'exécution).
N'importe JAMAIS execution_engine ou risk_engine, ni data_collector
(contrats import-linter) - la lecture du mode d'exécution courant via
`shared.execution_mode_state` ne viole pas ce contrat (c'est un module
`shared`, déjà lu par `execution_engine`, `risk_engine` et `portfolio`).

Depuis ADR-0010 : évalue tous les moteurs actifs (pas un seul), fusionne
leurs avis via meta_engine, applique la calibration active (chantier 3),
et écrit le résultat dans `decisions` sous une forme compatible avec
`risk_engine` (aucun changement requis côté risk_engine - cf. ADR-0010,
schéma additif).

Depuis ADR-0014/ADR-0015 : le mode d'exécution courant (paper/réel)
gouverne quel niveau de maturité du Confidence Lifecycle
(`shared.confidence_lifecycle`) est exploitable pour produire un verdict
'signal' - jamais 'collecting'/'preliminary' en mode réel. Voir
`_derive_verdict()` pour la logique complète.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime

import asyncpg
import redis.asyncio as redis

from decision_engine.thresholds import (
    evaluate_bootstrap_verdict,
    evaluate_verdict,
    is_data_fresh,
    is_excluded_from_fusion,
)
from feature_engine.registry import register_and_verify_features
from meta_engine.calibration_lookup import (
    apply_calibration_if_available,
    apply_calibration_if_valid,
    fetch_active_calibration,
)
from meta_engine.cost_estimation import estimate_expected_value, estimate_risk_reward_ratio, evaluate_costs
from meta_engine.cross_sectional import classify_cross_sectional_ranks
from meta_engine.fusion import fuse_opinions
from regime_engine.detector import RegimeResult
from regime_engine.main import compute_and_persist_regime
from shared.calibration_provider import CalibrationRun
from shared.confidence_lifecycle import COLLECTING, PRELIMINARY, VALIDATED, classify_calibration_maturity
from shared.exchange_config import ACTIVE_EXCHANGES
from shared.execution_mode_state import get_current_mode
from shared.fee_constants import (
    DOCUMENTED_FALLBACK,
    DOCUMENTED_FALLBACK_BINANCE_FUTURES_TAKER_FEE_BPS,
    DOCUMENTED_FALLBACK_TAKER_FEE_BPS,
)
from shared.symbol_mapping import BINANCE_NATIVE_TO_CANONICAL, HTX_NATIVE_TO_CANONICAL
from strategies.registry import ACTIVE_STRATEGIES, register_and_verify_strategies

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]
JOURNAL_CHANNEL = "events:journal"

EVALUATION_INTERVAL_SECONDS = 60  # aligné sur le cycle du Feature Builder (Phase 9)

# Symboles canoniques suivis par exchange (ADR-0012) - même registre que
# feature_engine/main.py ; jamais un seul EXCHANGE/SYMBOLS en dur.
_SYMBOLS_BY_EXCHANGE = {
    "htx": list(HTX_NATIVE_TO_CANONICAL.values()),
    "binance": list(BINANCE_NATIVE_TO_CANONICAL.values()),
}


async def main() -> None:
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    redis_client = redis.from_url(REDIS_URL)

    def publish_journal_event(event_type: str, payload: dict) -> None:
        asyncio.create_task(
            redis_client.publish(
                JOURNAL_CHANNEL,
                json.dumps(
                    {"source_module": "decision_engine", "event_type": event_type, "payload": payload},
                    default=str,
                ),
            )
        )

    feature_definition_ids = await register_and_verify_features(db_pool)
    strategy_ids = await register_and_verify_strategies(db_pool)
    await _ensure_lifecycle_rows(db_pool, strategy_ids)
    publish_journal_event(
        "decision_engine.started",
        {
            "features": list(feature_definition_ids.keys()),
            "strategies": list(strategy_ids.keys()),
            "exchanges": ACTIVE_EXCHANGES,
        },
    )

    while True:
        lifecycle_statuses = await _fetch_lifecycle_statuses(db_pool)
        for exchange in ACTIVE_EXCHANGES:
            symbols = _SYMBOLS_BY_EXCHANGE.get(exchange, [])
            # ADR-0017 : le classement cross-sectionnel a par nature besoin
            # de voir tous les symboles suivis au même instant - calculé une
            # seule fois par exchange par cycle, jamais recalculé par
            # symbole (contrairement aux features en série temporelle,
            # propres à chaque symbole).
            cross_sectional_ranks = await _fetch_cross_sectional_ranks(
                db_pool, exchange, symbols, feature_definition_ids.get("momentum")
            )
            for symbol in symbols:
                try:
                    await _evaluate_symbol(
                        db_pool,
                        exchange,
                        symbol,
                        feature_definition_ids,
                        strategy_ids,
                        publish_journal_event,
                        cross_sectional_ranks.get(symbol),
                        lifecycle_statuses,
                    )
                except Exception as exc:
                    logger.exception("Erreur d'évaluation pour %s/%s", exchange, symbol)
                    publish_journal_event(
                        "decision_engine.evaluation_error",
                        {"exchange": exchange, "symbol": symbol, "error": str(exc)},
                    )
        await asyncio.sleep(EVALUATION_INTERVAL_SECONDS)


# --- Étape 3 (16/08/2026) : Strategy Lifecycle - lu/initialisé en SQL
# direct, jamais par un import du package `strategy_lifecycle` (contrat
# import-linter 13, même principe que `fee_schedule`/`cost_model`,
# contrat 11). ---


async def _ensure_lifecycle_rows(db_pool: asyncpg.Pool, strategy_ids: dict[str, int]) -> None:
    """Initialise une ligne `strategy_lifecycle_state` pour toute
    stratégie active qui n'en a pas encore (idempotent, ON CONFLICT DO
    NOTHING) - toute stratégie déjà en production au moment où ce
    chantier est déployé démarre en 'experimental', jamais 'registered'
    (qui impliquerait qu'elle ne tourne pas encore, faux pour les
    moteurs déjà actifs). Appelé une seule fois au démarrage, pas à
    chaque cycle."""
    async with db_pool.acquire() as conn:
        for strategy_id in strategy_ids.values():
            await conn.execute(
                """
                INSERT INTO strategy_lifecycle_state (strategy_id, status, reason, sample_size)
                VALUES ($1, 'experimental', 'Initialisation automatique (Étape 3, 16/08/2026).', 0)
                ON CONFLICT (strategy_id) DO NOTHING;
                """,
                strategy_id,
            )


async def _fetch_lifecycle_statuses(db_pool: asyncpg.Pool) -> dict[int, str]:
    """Une requête par cycle, pas une par stratégie/symbole - même
    patron que `_fetch_cross_sectional_ranks` (ADR-0017)."""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT strategy_id, status FROM strategy_lifecycle_state;")
    return {row["strategy_id"]: row["status"] for row in rows}


async def _fetch_cross_sectional_ranks(
    db_pool: asyncpg.Pool, exchange: str, symbols: list[str], momentum_feature_definition_id: int | None
) -> dict[str, dict[str, float]]:
    """Récupère le dernier `momentum` connu de chaque symbole suivi sur cet
    exchange et en déduit un classement relatif (ADR-0017). Retourne un
    dict vide si `momentum` n'est pas (encore) enregistré comme feature
    active - jamais un blocage du cycle pour une feature en cours
    d'enregistrement."""
    if momentum_feature_definition_id is None:
        return {}

    momentum_by_symbol: dict[str, float] = {}
    async with db_pool.acquire() as conn:
        for symbol in symbols:
            row = await conn.fetchrow(
                """
                SELECT value FROM feature_values
                WHERE feature_definition_id = $1 AND exchange = $2 AND symbol = $3
                ORDER BY time DESC
                LIMIT 1;
                """,
                momentum_feature_definition_id,
                exchange,
                symbol,
            )
            if row is not None:
                momentum_by_symbol[symbol] = row["value"]

    return classify_cross_sectional_ranks(momentum_by_symbol)


async def _fetch_latest_features(
    db_pool: asyncpg.Pool, exchange: str, symbol: str, feature_definition_ids: dict[str, int]
) -> tuple[dict[str, float], dict[str, int], dict[str, datetime]]:
    """Retourne (features par nom, id de la ligne feature_values utilisée par nom, timestamp par nom)."""
    features: dict[str, float] = {}
    snapshot_ids: dict[str, int] = {}
    timestamps: dict[str, datetime] = {}

    async with db_pool.acquire() as conn:
        for name, definition_id in feature_definition_ids.items():
            row = await conn.fetchrow(
                """
                SELECT id, value, time FROM feature_values
                WHERE feature_definition_id = $1 AND exchange = $2 AND symbol = $3
                ORDER BY time DESC
                LIMIT 1;
                """,
                definition_id,
                exchange,
                symbol,
            )
            if row is not None:
                features[name] = row["value"]
                snapshot_ids[name] = row["id"]
                timestamps[name] = row["time"]

    return features, snapshot_ids, timestamps


def _derive_verdict(
    execution_mode: str,
    fused_score: float,
    calibration: CalibrationRun | None,
    expected_value: float | None,
    risk_reward_ratio: float | None,
) -> tuple[str, float | None, str, str]:
    """Détermine le verdict d'une MetaDecision (ADR-0014, ADR-0015).

    Fonction pure (aucun accès DB/horloge) - appelée par `_evaluate_symbol`
    une fois `fusion.suggested_side` connu (jamais `None`, cf. l'appelant).

    Retourne `(verdict, success_probability, calibration_maturity,
    verdict_reason)`. `verdict_reason` est toujours une explication en
    langage humain (principe directeur 1 : jamais un rejet silencieux),
    exposée par l'API d'explicabilité (`api/main.py`).

    Règle de gouvernance centrale (ADR-0014) :
    - mode 'real' : exige le niveau 'validated' du Confidence Lifecycle -
      comportement inchangé par rapport à ADR-0009/0010.
    - mode 'paper' (ou 'backtest') : accepte 'validated' ET 'preliminary'
      (probabilité calibrée disponible dès 5 trades clôturés, ADR-0015) ;
      si la calibration est encore 'collecting', se rabat sur le score
      brut fusionné (`evaluate_bootstrap_verdict`) plutôt que de refuser
      indéfiniment - c'est le mécanisme qui casse le deadlock initial.
    """
    maturity = classify_calibration_maturity(calibration)

    if expected_value is None or risk_reward_ratio is None:
        return "no_signal", None, maturity, "Coûts d'exécution non estimables (feature manquante)."

    if maturity == VALIDATED:
        success_probability = apply_calibration_if_valid(calibration, fused_score)
        verdict = evaluate_verdict(success_probability, expected_value, risk_reward_ratio)
        reason = (
            f"Calibration validée (n={calibration.sample_size}) appliquée : "
            f"probabilité calibrée {success_probability:.1%}."
        )
        return verdict, success_probability, maturity, reason

    if execution_mode == "real":
        return (
            "insufficient_calibration",
            None,
            maturity,
            (
                "Mode réel : requiert une calibration 'validated' (Confidence Lifecycle, "
                f"ADR-0015) - niveau actuel : '{maturity}'. Jamais de probabilité par défaut "
                "inventée (principe directeur 2)."
            ),
        )

    if maturity == PRELIMINARY:
        success_probability = apply_calibration_if_available(calibration, fused_score)
        verdict = evaluate_verdict(success_probability, expected_value, risk_reward_ratio)
        reason = (
            f"Mode {execution_mode} : calibration 'preliminary' (n={calibration.sample_size}/30, "
            f"ADR-0015) appliquée : probabilité calibrée {success_probability:.1%}, fortement "
            "régularisée vers le prior. Jamais utilisée en mode réel."
        )
        return verdict, success_probability, maturity, reason

    # maturity == "collecting" et execution_mode in {"paper", "backtest"} :
    # amorçage par score brut (ADR-0014) - jamais en mode réel.
    verdict = evaluate_bootstrap_verdict(fused_score, expected_value, risk_reward_ratio)
    reason = (
        f"Mode {execution_mode} : aucune calibration exploitable (niveau 'collecting', "
        "ADR-0015) - verdict de démarrage fondé sur le score brut fusionné "
        f"({fused_score:.2f}) plutôt qu'une probabilité calibrée (ADR-0014)."
    )
    return verdict, None, maturity, reason


async def _fetch_round_trip_fee_bps(
    db_pool: asyncpg.Pool, exchange: str, symbol: str, market_type: str = "spot"
) -> tuple[float, str]:
    """Frais round-trip réels (ADR-0016) - lit `fee_schedule` en SQL direct,
    jamais via un import de `cost_model` (contrat import-linter 11, même
    principe que `portfolio_snapshots` lu directement par `risk_engine`
    sans importer `portfolio.htx_provider`, contrat 7).

    Chantier de routage par market_type (16/08/2026) : `fee_schedule`
    reste scopé au spot uniquement (décision assumée à l'Étape 2 -
    "à mesurer quand Binance futures fees actually need measuring" -
    ce jour est arrivé avec `liquidation_cascade`). Pour
    `market_type='futures_perpetual'`, repli documenté immédiat
    (`DOCUMENTED_FALLBACK_BINANCE_FUTURES_TAKER_FEE_BPS`) - jamais une
    lecture de `fee_schedule` qui donnerait un tarif SPOT à une décision
    FUTURES (Binance futures ~5 bps taker vs HTX/Binance spot ~10-20 bps -
    une confusion aurait rendu l'estimation de coût presque 2 à 4 fois
    trop pessimiste, jamais neutre).

    Repli documenté et sourcé si `cost_model` n'a encore jamais tourné
    pour ce couple (exchange, symbole) en spot - jamais un blocage de la
    décision pour une donnée de frais manquante, mais toujours étiqueté
    comme un repli (`fee_source`), jamais confondu avec une mesure réelle."""
    if market_type == "futures_perpetual":
        return DOCUMENTED_FALLBACK_BINANCE_FUTURES_TAKER_FEE_BPS * 2, DOCUMENTED_FALLBACK

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT taker_fee_bps, source FROM fee_schedule WHERE exchange = $1 AND symbol = $2;",
            exchange,
            symbol,
        )
    if row is None:
        return DOCUMENTED_FALLBACK_TAKER_FEE_BPS * 2, DOCUMENTED_FALLBACK
    return row["taker_fee_bps"] * 2, row["source"]


async def _evaluate_symbol(
    db_pool: asyncpg.Pool,
    exchange: str,
    symbol: str,
    feature_definition_ids: dict[str, int],
    strategy_ids: dict[str, int],
    publish_journal_event,
    cross_sectional_rank: dict[str, float] | None = None,
    lifecycle_statuses: dict[int, str] | None = None,
) -> None:
    features, snapshot_ids, timestamps = await _fetch_latest_features(
        db_pool, exchange, symbol, feature_definition_ids
    )

    if not features:
        return  # rien à évaluer pour ce symbole pour l'instant - pas une erreur

    # ADR-0017 : `cross_sectional_rank`/`cross_sectional_spread` sont
    # calculés une fois par cycle (cf. `_fetch_cross_sectional_ranks`),
    # pas par ce symbole isolément - injectés ici comme deux features de
    # plus, exactement comme les autres (`momentum`, `spread_bps`...) :
    # aucune extension du contrat DecisionEngine/EngineOpinion n'est
    # nécessaire (ADR-0002, inchangé). Absent (univers pas encore prêt)
    # -> les deux clés restent simplement absentes du dict, comme pour
    # toute feature non encore disponible.
    if cross_sectional_rank is not None:
        features.update(cross_sectional_rank)

    now = datetime.now(tz=UTC)
    stale_features = [name for name, ts in timestamps.items() if not is_data_fresh(ts, now)]
    if stale_features:
        publish_journal_event(
            "decision_engine.stale_data", {"symbol": symbol, "stale_features": stale_features}
        )
        return  # jamais de décision sur une donnée qu'on sait périmée (Phase 11, §6)

    # --- Étape 0 : régime de marché (ADR-0011) - avant toute évaluation de moteur ---
    # Nécessite momentum et realized_volatility - si absentes, le régime
    # reste "unknown" sans persistance (rien de fiable à enregistrer).
    if "momentum" in features and "realized_volatility" in features:
        regime = await compute_and_persist_regime(
            db_pool,
            exchange,
            symbol,
            current_momentum=features["momentum"],
            current_volatility=features["realized_volatility"],
            momentum_feature_definition_id=feature_definition_ids["momentum"],
            volatility_feature_definition_id=feature_definition_ids["realized_volatility"],
        )
        publish_journal_event(
            "decision_engine.regime_detected",
            {"symbol": symbol, "regime_type": regime.regime_type, "confidence": regime.confidence},
        )
    else:
        regime = RegimeResult(
            regime_type="unknown", confidence=0.0, trend="unknown", volatility_level="unknown"
        )

    # --- Étape 1 : chaque moteur produit un avis indépendant (ADR-0010),
    # filtré par régime autorisé (ADR-0011 - ensemble vide = pas de
    # restriction, comportement inchangé pour les moteurs existants) et
    # par statut de Strategy Lifecycle (Étape 3, 16/08/2026) ; groupé par
    # market_type (chantier de routage, 16/08/2026) - jamais un avis
    # spot fusionné avec un avis futures dans la même décision (deux
    # instruments différents, deux moteurs d'exécution différents).
    opinions_by_market_type: dict[str, dict[str, list]] = {}
    lifecycle_statuses = lifecycle_statuses or {}
    execution_mode = await get_current_mode(db_pool)

    async with db_pool.acquire() as conn:
        for engine in ACTIVE_STRATEGIES:
            allowed = engine.metadata.allowed_regimes
            if allowed and regime.regime_type not in allowed:
                publish_journal_event(
                    "decision_engine.engine_skipped_regime",
                    {"symbol": symbol, "engine": engine.metadata.name, "regime_type": regime.regime_type},
                )
                continue

            opinion = engine.evaluate(features)

            if opinion is None:
                publish_journal_event(
                    "decision_engine.no_opinion",
                    {"symbol": symbol, "engine": engine.metadata.name, "features": features},
                )
                continue

            opinion_id = await conn.fetchval(
                """
                INSERT INTO engine_opinions
                    (strategy_id, exchange, symbol, time, suggested_side, score, confidence, uncertainty, rationale)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
                RETURNING id;
                """,
                strategy_ids[engine.metadata.name],
                exchange,
                symbol,
                now,
                opinion.suggested_side.value,
                opinion.score,
                opinion.confidence,
                opinion.uncertainty,
                json.dumps(opinion.rationale),
            )

            # L'avis est toujours calculé et persisté (traçabilité complète,
            # future résurrection éventuelle) - seule sa participation à la
            # fusion dépend du statut de lifecycle (jamais l'inverse : on ne
            # prive jamais le système de la donnée elle-même).
            lifecycle_status = lifecycle_statuses.get(strategy_ids[engine.metadata.name])
            if is_excluded_from_fusion(lifecycle_status, execution_mode):
                publish_journal_event(
                    "decision_engine.engine_excluded_from_fusion_lifecycle_status",
                    {
                        "symbol": symbol,
                        "engine": engine.metadata.name,
                        "lifecycle_status": lifecycle_status,
                        "execution_mode": execution_mode,
                    },
                )
                continue

            group = opinions_by_market_type.setdefault(
                engine.metadata.market_type, {"opinions": [], "engine_names": [], "opinion_ids": []}
            )
            group["opinions"].append(opinion)
            group["engine_names"].append(engine.metadata.name)
            group["opinion_ids"].append(opinion_id)

    if not opinions_by_market_type:
        return  # aucun moteur n'a produit d'avis exploitable ce cycle - résultat normal, pas une erreur

    for market_type, group in opinions_by_market_type.items():
        await _fuse_and_persist_decision(
            db_pool,
            exchange,
            symbol,
            market_type,
            group["opinions"],
            group["engine_names"],
            group["opinion_ids"],
            features,
            snapshot_ids,
            now,
            execution_mode,
            regime,
        )


async def _fuse_and_persist_decision(
    db_pool: asyncpg.Pool,
    exchange: str,
    symbol: str,
    market_type: str,
    opinions: list,
    engine_names: list[str],
    opinion_ids: list[int],
    features: dict[str, float],
    snapshot_ids: dict[str, int],
    now: datetime,
    execution_mode: str,
    regime: RegimeResult,
) -> None:
    """Étapes 2-5 (fusion -> verdict -> persistance meta_decisions/
    decisions/cost_estimates), extraites de `_evaluate_symbol` pour être
    appelées une fois par groupe de `market_type` (chantier de routage,
    16/08/2026) - avant ce chantier, cette logique tournait une seule
    fois par symbole, implicitement toujours en spot."""
    # --- Étape 2 : fusion (ADR-0010) ---
    fusion = fuse_opinions(opinions, engine_names)

    # Chantier de routage (16/08/2026) : seule une valeur EXPLICITEMENT
    # non-spot (aujourd'hui : "futures_perpetual", liquidation_cascade)
    # est écrite dans meta_decisions/decisions - "spot" (la valeur par
    # défaut d'EngineMetadata.market_type, celle des 3 moteurs déjà
    # actifs) est traduit en NULL. Nécessaire pour ne pas régresser
    # silencieusement ADR-0019 (`FUTURES_ROUTING_ENABLED`) : si une
    # valeur "spot" explicite était écrite pour ces 3 moteurs, elle
    # court-circuiterait pour toujours l'heuristique `determine_market_type`
    # de `risk_engine` (y compris pour un SELL sans position, que le
    # flag autorise aujourd'hui à router vers le futures) - alors que
    # l'absence d'écriture (NULL) préserve exactement le comportement
    # actuel, flag activé ou non.
    persisted_market_type = market_type if market_type != "spot" else None

    calibration_row_id: int | None = None
    success_probability: float | None = None
    round_trip_fee_bps, fee_source = await _fetch_round_trip_fee_bps(db_pool, exchange, symbol, market_type)
    expected_value = estimate_expected_value(features, round_trip_fee_bps)
    risk_reward_ratio = estimate_risk_reward_ratio(features)

    if fusion.suggested_side is None:
        meta_verdict = "no_signal"  # désaccord entre moteurs, ou aucune confiance exploitable
        calibration_maturity = COLLECTING
        verdict_reason = "Désaccord entre moteurs ou aucune confiance exploitable côté fusion."
    else:
        # Invariant de fuse_opinions (meta_engine/fusion.py) : fused_score
        # n'est jamais None quand suggested_side ne l'est pas - les deux
        # champs sont toujours renseignés ensemble.
        assert fusion.fused_score is not None
        calibration_lookup = await fetch_active_calibration(db_pool)
        calibration = None
        if calibration_lookup is not None:
            calibration_row_id, calibration = calibration_lookup

        # ADR-0014/ADR-0015 : la logique complète de gouvernance (mode
        # d'exécution x niveau de maturité) vit dans `_derive_verdict`,
        # fonction pure testable en isolation - jamais dupliquée ici.
        meta_verdict, success_probability, calibration_maturity, verdict_reason = _derive_verdict(
            execution_mode, fusion.fused_score, calibration, expected_value, risk_reward_ratio
        )

    # --- Étape 3 : persistance de la MetaDecision (ADR-0010, ADR-0014, ADR-0015) ---
    async with db_pool.acquire() as conn:
        meta_decision_id = await conn.fetchval(
            """
            INSERT INTO meta_decisions
                (exchange, symbol, time, fusion_method, fused_score, suggested_side,
                 weights_applied, contributing_opinion_ids, calibration_run_id, success_probability,
                 verdict, calibration_maturity, verdict_reason, execution_mode,
                 regime_type, regime_confidence, market_type)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)
            RETURNING id;
            """,
            exchange,
            symbol,
            now,
            "confidence_weighted_average",
            fusion.fused_score,
            fusion.suggested_side.value if fusion.suggested_side else None,
            json.dumps(fusion.weights_applied),
            opinion_ids,
            calibration_row_id,
            success_probability,
            meta_verdict,
            calibration_maturity,
            verdict_reason,
            execution_mode,
            regime.regime_type,
            regime.confidence,
            persisted_market_type,
        )

        # --- Étape 4 : compatibilité `decisions` (ADR-0010, schéma additif) ---
        # `decisions.verdict` ne connaît que 'signal'/'no_signal' (contrainte
        # historique inchangée) - 'insufficient_calibration' s'y traduit en
        # 'no_signal' ; la nuance complète reste disponible dans
        # `meta_decisions.verdict`/`meta_decisions.verdict_reason`.
        # `strategy_id` est NULL pour toute décision issue d'une fusion
        # (jamais un choix arbitraire entre les moteurs contributeurs).
        decisions_verdict = "signal" if meta_verdict == "signal" else "no_signal"
        used_snapshot_ids = [snapshot_ids[name] for name in features if name in snapshot_ids]

        decision_id = await conn.fetchval(
            """
            INSERT INTO decisions
                (strategy_id, meta_decision_id, exchange, symbol, time, success_probability,
                 expected_value, risk_reward_ratio, verdict, feature_snapshot_ids, suggested_side, market_type)
            VALUES (NULL, $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING id;
            """,
            meta_decision_id,
            exchange,
            symbol,
            now,
            success_probability if success_probability is not None else 0.0,
            expected_value or 0.0,
            risk_reward_ratio or 0.0,
            decisions_verdict,
            used_snapshot_ids,
            fusion.suggested_side.value if fusion.suggested_side else "buy",
            persisted_market_type,
        )

        # --- Étape 5 : traçabilité des coûts (ADR-0016, chantier CostModel
        # unique du 16/08/2026) - un seul calcul (`evaluate_costs`, testé
        # en isolation dans `meta_engine/cost_estimation.py`), jamais
        # recalculé séparément ici (avant ce chantier, `net_margin_bps`
        # était redérivé indépendamment de `expected_value` - deux
        # expressions mathématiquement équivalentes mais non
        # synchronisées par un test). Toujours purement observationnel :
        # ne bloque jamais une décision ici, seulement pour observer
        # l'agrégat une fois assez de décisions accumulées (cf. étude
        # CostModel §4).
        raw_edge_bps = abs(features["momentum"]) * 10_000 if features.get("momentum") is not None else None
        cost_evaluation = None
        if raw_edge_bps is not None and features.get("spread_bps") is not None:
            cost_evaluation = evaluate_costs(
                raw_edge_bps=raw_edge_bps,
                spread_bps=features["spread_bps"],
                round_trip_fee_bps=round_trip_fee_bps,
            )
        await conn.execute(
            """
            INSERT INTO cost_estimates
                (decision_id, raw_edge_bps, fee_bps, funding_impact_bps, net_margin_bps, cleared_costs, fee_source)
            VALUES ($1, $2, $3, $4, $5, $6, $7);
            """,
            decision_id,
            raw_edge_bps,
            round_trip_fee_bps,
            cost_evaluation.funding_impact_bps if cost_evaluation is not None else 0.0,
            cost_evaluation.net_edge_bps if cost_evaluation is not None else None,
            cost_evaluation.cleared_costs if cost_evaluation is not None else False,
            fee_source,
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
