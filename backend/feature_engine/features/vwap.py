from shared.feature import Feature, FeatureMetadata

WINDOW_SIZE = 20  # candles 1m - cohérent avec RealizedVolatility (Phase 9 §4)


class Vwap(Feature):
    """Prix moyen pondéré par le volume sur la fenêtre glissante (Phase 9, §4).

    market_data attendu : {"closes": [float, ...], "volumes": [float, ...]}
    (même longueur, ordre chronologique).
    """

    metadata = FeatureMetadata(
        name="vwap",
        version=1,
        description=f"Prix moyen pondéré par le volume sur les {WINDOW_SIZE} dernières candles 1m.",
    )

    def compute(self, market_data: dict) -> float | None:
        closes = market_data.get("closes") or []
        volumes = market_data.get("volumes") or []
        if len(closes) != len(volumes) or len(closes) < WINDOW_SIZE:
            return None

        recent_closes = closes[-WINDOW_SIZE:]
        recent_volumes = volumes[-WINDOW_SIZE:]
        total_volume = sum(recent_volumes)
        if total_volume == 0:
            return None

        weighted_sum = sum(price * volume for price, volume in zip(recent_closes, recent_volumes))
        return weighted_sum / total_volume
