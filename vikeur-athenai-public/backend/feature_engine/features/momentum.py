from shared.feature import Feature, FeatureMetadata

LOOKBACK_PERIODS = 10  # candles 1m - valeur de départ, à calibrer en Phase 14 (Phase 9 §7)


class Momentum(Feature):
    """Variation relative du prix de clôture sur LOOKBACK_PERIODS périodes
    (Phase 9, §4).

    market_data attendu : {"closes": [float, ...]} (ordre chronologique,
    au moins LOOKBACK_PERIODS + 1 valeurs).
    """

    metadata = FeatureMetadata(
        name="momentum",
        version=1,
        description=f"(close_actuel - close_il_y_a_{LOOKBACK_PERIODS}_periodes) / close_il_y_a_{LOOKBACK_PERIODS}_periodes.",
    )

    def compute(self, market_data: dict) -> float | None:
        closes = market_data.get("closes") or []
        if len(closes) < LOOKBACK_PERIODS + 1:
            return None

        current_close = closes[-1]
        past_close = closes[-(LOOKBACK_PERIODS + 1)]
        if past_close == 0:
            return None

        return (current_close - past_close) / past_close
