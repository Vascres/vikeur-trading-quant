from shared.feature import Feature, FeatureMetadata


class OrderFlowImbalance(Feature):
    """Déséquilibre entre volume acheteur et vendeur sur les N premiers
    niveaux du carnet d'ordres (Phase 9, §4).

    market_data attendu : {"bids": [[prix, quantite], ...], "asks": [[prix, quantite], ...]}
    (déjà limité aux N premiers niveaux par l'appelant, ex. top 20 - Phase 6 §5.1).

    Résultat dans [-1, 1] : positif = pression acheteuse dominante,
    négatif = pression vendeuse dominante.
    """

    metadata = FeatureMetadata(
        name="order_flow_imbalance",
        version=1,
        description="(volume_bid - volume_ask) / (volume_bid + volume_ask) sur les niveaux fournis du carnet.",
    )

    def compute(self, market_data: dict) -> float | None:
        bids = market_data.get("bids") or []
        asks = market_data.get("asks") or []
        if not bids or not asks:
            return None

        bid_volume = sum(quantity for _, quantity in bids)
        ask_volume = sum(quantity for _, quantity in asks)
        total_volume = bid_volume + ask_volume
        if total_volume == 0:
            return None

        return (bid_volume - ask_volume) / total_volume
