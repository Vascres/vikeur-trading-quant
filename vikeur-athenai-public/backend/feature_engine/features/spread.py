from shared.feature import Feature, FeatureMetadata


class SpreadBps(Feature):
    """Écart bid/ask relatif, en points de base (Phase 9, §4).

    market_data attendu : {"best_bid": float, "best_ask": float}
    (extrait du snapshot order_book_snapshots par l'appelant - cette
    fonction reste pure et ne connaît pas le format JSONB brut).
    """

    metadata = FeatureMetadata(
        name="spread_bps",
        version=1,
        description="Écart bid/ask relatif au prix médian, exprimé en points de base (1 bps = 0.01%).",
    )

    def compute(self, market_data: dict) -> float | None:
        best_bid = market_data.get("best_bid")
        best_ask = market_data.get("best_ask")
        if best_bid is None or best_ask is None or best_bid <= 0:
            return None

        mid_price = (best_bid + best_ask) / 2
        if mid_price == 0:
            return None

        return ((best_ask - best_bid) / mid_price) * 10_000
