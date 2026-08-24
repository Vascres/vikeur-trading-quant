from shared.feature import Feature, FeatureMetadata


class LiquidationCascadeIntensity(Feature):
    """Somme du notionnel liquidé (USD) sur la fenêtre récente fournie
    par l'appelant (chantier de données Liquidation Cascade, 16/08/2026 -
    mandat §28, "moteur phare" candidat).

    market_data attendu : {"recent_liquidation_notionals": [float, ...]}
    - déjà filtré à la fenêtre temporelle pertinente par l'appelant
    (`feature_engine/main.py`, requête SQL `event_time >= now() - X`) -
    cette feature ne connaît JAMAIS l'horloge système elle-même (même
    exigence de pureté que `momentum.py`, qui reçoit des `closes`
    déjà limités par la requête appelante, pas un accès direct à la DB).

    Une liste vide est un résultat NORMAL (aucune liquidation sur la
    fenêtre, y compris sur un exchange sans flux de liquidation collecté
    comme HTX aujourd'hui) - retourne 0.0, jamais None : l'absence de
    liquidation est une donnée réelle, pas une donnée manquante.

    Limitation assumée, héritée de la donnée elle-même (documentée dans
    `data_collector/adapters/binance_futures.py`) : le flux Binance
    forceOrder ne pousse que la PLUS GROSSE liquidation par symbole
    toutes les 1000ms - cette feature mesure donc une intensité
    MINIMALE, jamais un décompte exhaustif du volume réellement liquidé
    pendant une cascade.
    """

    metadata = FeatureMetadata(
        name="liquidation_cascade_intensity",
        version=1,
        description="Somme du notionnel liquidé (USD) sur la fenêtre récente fournie par l'appelant.",
    )

    def compute(self, market_data: dict) -> float | None:
        notionals = market_data.get("recent_liquidation_notionals")
        if notionals is None:
            return None  # clé absente = appelant n'a pas fourni la donnée, distinct d'une fenêtre vide
        return float(sum(notionals))
