"""Tests de regime_engine.detector.detect_regime (ADR-0011)."""

from regime_engine.detector import detect_regime


def _flat_history(n: int, value: float) -> list[float]:
    return [value] * n


def test_unknown_regime_when_history_too_short():
    result = detect_regime(
        current_momentum=0.02,
        momentum_history=[0.01] * 10,
        current_volatility=0.01,
        volatility_history=[0.01] * 10,
        minimum_history_size=50,
    )
    assert result.regime_type == "unknown"
    assert result.confidence == 0.0


def test_bullish_high_volatility_at_extremes():
    # Momentum history concentrée autour de petites valeurs, la valeur
    # courante nettement plus grande et positive -> tendance haussière nette.
    momentum_history = [0.001] * 60
    volatility_history = [0.005] * 60

    result = detect_regime(
        current_momentum=0.05,
        momentum_history=momentum_history,
        current_volatility=0.05,
        volatility_history=volatility_history,
    )

    assert result.trend == "bullish"
    assert result.volatility_level == "high"
    assert result.regime_type == "bullish_high_volatility"
    assert result.confidence > 0.9


def test_bearish_low_volatility():
    momentum_history = [0.05] * 60  # historique de forte amplitude
    volatility_history = [0.05] * 60

    result = detect_regime(
        current_momentum=-0.06,  # amplitude comparable ou légèrement supérieure, mais négative
        momentum_history=momentum_history,
        current_volatility=0.001,  # nettement sous l'historique -> faible volatilité
        volatility_history=volatility_history,
    )

    assert result.trend == "bearish"
    assert result.volatility_level == "low"
    assert result.regime_type == "bearish_low_volatility"


def test_sideways_when_momentum_typical():
    # La valeur courante est très proche de la médiane historique -> latéral.
    momentum_history = [0.01, -0.01] * 30
    volatility_history = [0.01] * 60

    result = detect_regime(
        current_momentum=0.0,
        momentum_history=momentum_history,
        current_volatility=0.01,
        volatility_history=volatility_history,
    )

    assert result.trend == "sideways"
    assert "sideways" in result.regime_type


def test_normal_volatility_near_median():
    momentum_history = [0.001] * 60
    volatility_history = list(range(1, 61))  # 1..60, médiane autour de 30/31

    result = detect_regime(
        current_momentum=0.001,
        momentum_history=momentum_history,
        current_volatility=30,
        volatility_history=[float(v) for v in volatility_history],
    )

    assert result.volatility_level == "normal"


def test_confidence_is_zero_to_one_range():
    momentum_history = [0.01] * 60
    volatility_history = [0.01] * 60

    result = detect_regime(
        current_momentum=0.5,
        momentum_history=momentum_history,
        current_volatility=0.5,
        volatility_history=volatility_history,
    )

    assert 0.0 <= result.confidence <= 1.0
