"""Calculs de marge et de prix de liquidation pour les futures perpétuels
(Étapes 7-8 du plan validé le 16/08/2026, mandat §8 "La Logique Futures").

Fonctions pures, testées en isolation - aucun accès DB/réseau/horloge,
même exigence que `shared/order_book.py`. Placées dans `shared/` (pas
`execution_engine/` ni `risk_engine/`) car elles n'ont aucune raison
d'être limitées par la couche d'import-linter qui sépare ces deux
modules - un calcul de prix de liquidation est une fonction mathématique
pure, pas une décision d'exécution ou de risque.

Limitation assumée et volontaire (cf. `data_collector/adapters/
binance_futures.py`, docstring du module) : ces fonctions sont
désormais câblées dans le Risk Engine (`FuturesNotionalExposureCapRule`
vérifie la marge requise à `MAX_LEVERAGE`, pas seulement le notionnel
brut, depuis la décision CTO du 16/08/2026) - mais `MAX_LEVERAGE` N'EST
PAS encore transmis aux adaptateurs (HTX et Binance envoient toujours
`lever_rate=1`/`leverage=1` à l'exchange, cf. docstring de
`MAX_LEVERAGE` ci-dessous). Le filet de sécurité qui rendrait un levier
réel sûr - un stop-loss automatique posé avant la liquidation (mandat
§9, "triptyque d'ordres") - n'existe pas encore dans `execution_engine`.
"""

from __future__ import annotations

from decimal import Decimal

from shared.futures_adapter import PositionSide

# Décision CTO (16/08/2026, Étapes 7-8) : plafond système du levier
# futures. Remplace l'invariant ADR-0018 "jamais autre chose que 1x" -
# décision consciente, documentée, pas un contournement silencieux.
#
# Choix de 2x plutôt que 3x+ (mandat plafonne explicitement à 3x, "jamais
# activer automatiquement un levier élevé") : à 2x, la marge de sécurité
# avant liquidation reste large (~50% sur un actif majeur, cf.
# `compute_liquidation_price`) - à 5x elle tombe à ~20%, où une journée
# de volatilité normale peut suffire. Aucune stratégie n'a encore
# démontré d'edge réel (Strategy Lifecycle, Étape 3) - payer un risque
# de liquidation plus élevé sans preuve d'edge serait un risque non
# rémunéré, jamais justifié tant que cette preuve n'existe pas.
#
# IMPORTANT - séquencement délibéré : cette constante N'EST PAS encore
# utilisée par `HTXFuturesAdapter.place_order`/`BinanceFuturesAdapter.
# place_order`, qui continuent d'envoyer `lever_rate=1`/`leverage=1` à
# l'exchange. Le filet de sécurité qui rend 2x réellement sûr - un
# stop-loss automatique posé systématiquement avant le prix de
# liquidation (mandat §9, "triptyque d'ordres") - n'existe pas encore
# dans `execution_engine`. Cette constante prépare le terrain (schéma,
# règles de risque) sans activer le levier réel ; le faire basculer dans
# les adaptateurs sans ce filet serait exactement le raccourci que le
# mandat interdit.
MAX_LEVERAGE = 2

# Levier RÉELLEMENT envoyé à l'exchange aujourd'hui par les deux
# adaptateurs futures (`HTXFuturesAdapter.place_order`:`lever_rate: 1`,
# `BinanceFuturesAdapter.place_order`:`set_leverage(symbol, leverage=1)`)
# - distinct de `MAX_LEVERAGE` ci-dessus (le plafond système désormais
# autorisé côté Risk Engine). Tant que les adaptateurs n'envoient pas
# `MAX_LEVERAGE`, tout calcul de marge/liquidation pour une position
# réellement ouverte doit utiliser CETTE constante, pas `MAX_LEVERAGE` -
# sinon le stop-loss et le prix de liquidation affichés seraient calculés
# pour un levier qui n'est pas celui réellement engagé sur l'exchange.
ACTUAL_LEVERAGE = 1

# Triptyque d'ordres (mandat §8-9, 16/08/2026) : fraction de la marge
# engagée au-delà de laquelle le stop-loss automatique se déclenche.
# Choisi au milieu de la fourchette du mandat ("perte maximale de 3 à
# 5$" sur une marge de 75$, soit 4% à 6,7%) - valeur de départ prudente,
# comme chaque autre seuil de ce projet, à recalibrer avec des données
# réelles plutôt qu'un exemple unique.
MAX_LOSS_FRACTION_OF_MARGIN = Decimal("0.05")

# Taux de marge de maintenance Binance USDⓈ-M standard (palier de base,
# BTC/ETH, notionnel le plus faible) - confirmé par la documentation
# Binance au moment de l'écriture. Ce taux augmente par palier de
# notionnel (documentation Binance "Notional and Leverage Brackets") -
# une valeur unique ici est une simplification assumée, suffisante pour
# un compte de quelques centaines de dollars (toujours dans le palier
# de base), à revoir si la plateforme opère un jour à un notionnel plus
# élevé.
DEFAULT_MAINTENANCE_MARGIN_RATE = Decimal("0.004")  # 0,4%


def compute_required_margin(notional: Decimal, leverage: int) -> Decimal:
    """Marge à engager pour ouvrir une position de ce notionnel à ce
    levier - mandat §8 : "Margin Required = notionnel / levier"."""
    if leverage <= 0:
        raise ValueError(f"Le levier doit être strictement positif, reçu {leverage}.")
    return notional / Decimal(leverage)


def compute_liquidation_price(
    entry_price: Decimal,
    leverage: int,
    side: PositionSide,
    maintenance_margin_rate: Decimal = DEFAULT_MAINTENANCE_MARGIN_RATE,
) -> Decimal:
    """Prix auquel la marge isolée tombe sous la marge de maintenance de
    l'exchange (mandat §8, exemple vérifié : ETH à 3000$, levier 2x,
    marge de maintenance 0,4% -> liquidation vers 1512$).

    Formule simplifiée (ignore les frais d'ouverture/clôture et le
    funding accumulé, cf. limitation assumée ci-dessus) :
    - LONG  : entry * (1 - 1/levier + taux_marge_maintenance)
    - SHORT : entry * (1 + 1/levier - taux_marge_maintenance)
    """
    if leverage <= 0:
        raise ValueError(f"Le levier doit être strictement positif, reçu {leverage}.")

    inverse_leverage = Decimal(1) / Decimal(leverage)
    if side == PositionSide.LONG:
        return entry_price * (Decimal(1) - inverse_leverage + maintenance_margin_rate)
    return entry_price * (Decimal(1) + inverse_leverage - maintenance_margin_rate)


def compute_max_loss_stop_price(
    entry_price: Decimal,
    leverage: int,
    side: PositionSide,
    max_loss_fraction_of_margin: Decimal,
) -> Decimal:
    """Prix de stop-loss garantissant que la perte reste plafonnée à
    `max_loss_fraction_of_margin` de la marge engagée, TOUJOURS avant le
    prix de liquidation de l'exchange (mandat §8 : "Le Risk Engine
    refuse d'être liquidé par l'exchange, qui facture des frais de
    liquidation punitifs").

    L'appelant est responsable de vérifier que le prix retourné reste
    bien au-dessus (LONG) ou en-dessous (SHORT) de
    `compute_liquidation_price` - cette fonction ne le garantit pas
    automatiquement pour un `max_loss_fraction_of_margin` mal choisi
    (ex. proche de 100%), jamais une hypothèse silencieuse.
    """
    if leverage <= 0:
        raise ValueError(f"Le levier doit être strictement positif, reçu {leverage}.")

    price_move_fraction = max_loss_fraction_of_margin / Decimal(leverage)
    if side == PositionSide.LONG:
        return entry_price * (Decimal(1) - price_move_fraction)
    return entry_price * (Decimal(1) + price_move_fraction)
