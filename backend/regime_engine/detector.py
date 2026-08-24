"""Détecteur de régime de marché (ADR-0011).

Fonction pure : aucun accès DB/réseau/horloge - même exigence que
Feature/DecisionEngine. Taxonomie volontairement réduite à 2 dimensions
honnêtement soutenues par les features disponibles aujourd'hui (tendance,
volatilité) plutôt que les 10 catégories aspirationnelles de la mission -
cf. ADR-0011 pour la justification complète et ce qui est différé.
"""

from __future__ import annotations

from dataclasses import dataclass

# En dessous de ce nombre d'observations historiques, la classification
# n'est pas jugée fiable - régime "unknown" plutôt qu'une classification
# inventée (principe directeur 2 : refuser plutôt qu'inventer).
MINIMUM_HISTORY_SIZE = 50

# |momentum| en dessous de ce percentile de sa propre distribution
# historique -> pas de tendance nette (marché latéral).
SIDEWAYS_PERCENTILE_THRESHOLD = 0.40

HIGH_VOLATILITY_PERCENTILE_THRESHOLD = 0.75
LOW_VOLATILITY_PERCENTILE_THRESHOLD = 0.25


@dataclass(frozen=True)
class RegimeResult:
    regime_type: str  # ex. "bullish_high_volatility", "sideways_normal_volatility", "unknown"
    confidence: float  # dans [0, 1] - 0 si régime "unknown"
    trend: str  # "bullish" | "bearish" | "sideways" | "unknown"
    volatility_level: str  # "high" | "normal" | "low" | "unknown"


def _percentile_rank(value: float, history: list[float]) -> float:
    """Proportion de `history` inférieure ou égale à `value` - non
    paramétrique, robuste à l'asymétrie (retenu plutôt qu'un z-score,
    cf. ADR-0011)."""
    below_or_equal = sum(1 for h in history if h <= value)
    return below_or_equal / len(history)


def detect_regime(
    current_momentum: float,
    momentum_history: list[float],
    current_volatility: float,
    volatility_history: list[float],
    minimum_history_size: int = MINIMUM_HISTORY_SIZE,
) -> RegimeResult:
    if len(momentum_history) < minimum_history_size or len(volatility_history) < minimum_history_size:
        return RegimeResult(
            regime_type="unknown", confidence=0.0, trend="unknown", volatility_level="unknown"
        )

    abs_momentum_history = [abs(m) for m in momentum_history]
    momentum_percentile = _percentile_rank(abs(current_momentum), abs_momentum_history)

    if momentum_percentile < SIDEWAYS_PERCENTILE_THRESHOLD:
        trend = "sideways"
    elif current_momentum > 0:
        trend = "bullish"
    else:
        trend = "bearish"

    volatility_percentile = _percentile_rank(current_volatility, volatility_history)
    if volatility_percentile >= HIGH_VOLATILITY_PERCENTILE_THRESHOLD:
        volatility_level = "high"
    elif volatility_percentile <= LOW_VOLATILITY_PERCENTILE_THRESHOLD:
        volatility_level = "low"
    else:
        volatility_level = "normal"

    # Confiance dérivée directement de la distance au centre de la
    # distribution historique (0 près de la médiane, 1 aux extrêmes) -
    # transparente et reproductible, pas une formule inventée séparément
    # de la classification elle-même.
    trend_confidence = abs(momentum_percentile - 0.5) * 2
    volatility_confidence = abs(volatility_percentile - 0.5) * 2
    confidence = min(trend_confidence, volatility_confidence)

    return RegimeResult(
        regime_type=f"{trend}_{volatility_level}_volatility",
        confidence=confidence,
        trend=trend,
        volatility_level=volatility_level,
    )
