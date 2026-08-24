import math

from shared.feature import Feature, FeatureMetadata

WINDOW_SIZE = 20  # nombre de candles 1m - valeur de départ, à calibrer en Phase 14 (Phase 9 §7)


class RealizedVolatility(Feature):
    """Volatilité réalisée : écart-type des rendements logarithmiques
    sur les WINDOW_SIZE dernières candles 1 minute (Phase 9, §4).

    market_data attendu : {"closes": [float, ...]}  (ordre chronologique,
    au moins WINDOW_SIZE + 1 valeurs pour calculer WINDOW_SIZE rendements)
    """

    metadata = FeatureMetadata(
        name="realized_volatility",
        version=2,  # v1 -> v2 : reformatage black (espace dans la notation de slice)
        # a changé le hash du code source sans changer la logique de calcul -
        # le mécanisme de versionnement l'a détecté à raison (Phase 4 §5.2,
        # Phase 9 §3) ; incrémenté en conséquence, découvert en déployant.
        description=f"Écart-type des rendements log sur les {WINDOW_SIZE} dernières candles 1m.",
    )

    def compute(self, market_data: dict) -> float | None:
        closes = market_data.get("closes") or []
        if len(closes) < WINDOW_SIZE + 1:
            return None

        recent_closes = closes[-(WINDOW_SIZE + 1) :]
        log_returns = [
            math.log(recent_closes[i] / recent_closes[i - 1])
            for i in range(1, len(recent_closes))
            if recent_closes[i - 1] > 0
        ]
        if len(log_returns) < 2:
            return None

        mean_return = sum(log_returns) / len(log_returns)
        variance = sum((r - mean_return) ** 2 for r in log_returns) / (len(log_returns) - 1)
        return math.sqrt(variance)
