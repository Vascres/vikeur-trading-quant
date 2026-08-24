"""Constantes de provenance des frais (ADR-0016) - dans `shared/` plutôt
que dans `cost_model/` pour que `decision_engine` puisse lire la table
`fee_schedule` (SQL direct, jamais un import de `cost_model`) sans violer
la couche stricte déjà imposée par import-linter (contrat 4) - même
principe que `portfolio_snapshots`, lue en SQL direct par `risk_engine`
sans jamais importer `portfolio.htx_provider` (contrat 7).
"""

from __future__ import annotations

MEASURED_API = "measured_api"  # frais lus en direct sur le compte exchange
DOCUMENTED_FALLBACK = "documented_fallback"  # repli si l'API est indisponible

# Repli explicite et sourcé (jamais une intuition) : tarif HTX standard
# publié (palier "Prime 0", non-VIP) - utilisé uniquement si l'appel API
# authentifié échoue, ou si aucune mesure n'a encore été persistée par
# `cost_model` (ex. tout premier démarrage). Jamais silencieusement
# confondu avec une mesure réelle (cf. `fee_source` partout où ce
# repli est utilisé).
DOCUMENTED_FALLBACK_TAKER_FEE_BPS = 20.0  # 0,20% - HTX spot, palier de base, par jambe

# ADR-0021 : futures (perpétuels USDT-margined HTX) - aucun endpoint
# authentifié confirmé pour interroger le palier réel du compte sur le
# futures (contrairement au spot, ADR-0016) - recherché avant d'écrire
# ce code, pas supposé. Reste donc un repli documenté en permanence pour
# l'instant, jamais étiqueté `MEASURED_API` - tarif HTX standard publié
# (palier "Prime 0", non-VIP), confirmé par plusieurs sources
# indépendantes (0,02% maker / 0,06% taker), pas une intuition.
DOCUMENTED_FALLBACK_FUTURES_MAKER_FEE_BPS = 2.0  # 0,02% - HTX futures, palier de base
DOCUMENTED_FALLBACK_FUTURES_TAKER_FEE_BPS = 6.0  # 0,06% - HTX futures, palier de base

# Chantier CostModel unique (16/08/2026, extension à Binance) - tarif
# Binance spot standard publié (VIP 0, sans remise BNB) : 0,10% maker ET
# taker, confirmé par plusieurs sources indépendantes au moment de
# l'écriture. Utilisé uniquement si l'appel API authentifié échoue (cf.
# `cost_model/binance_fee_fetcher.py`), jamais au démarrage normal -
# même principe que le repli HTX ci-dessus.
DOCUMENTED_FALLBACK_BINANCE_SPOT_TAKER_FEE_BPS = 10.0  # 0,10% - Binance spot, palier de base, par jambe

# Binance USDⓈ-M Futures - posé en préparation du chantier Binance
# Futures (Étapes 7-8 du plan) : aucun adaptateur futures Binance
# n'existe encore (`data_collector/adapters/futures_factory.py` ne
# référence que HTX) - ces deux constantes ne sont donc consommées nulle
# part pour l'instant. Tarif standard publié (VIP 0) : 0,02% maker /
# 0,05% taker, confirmé par plusieurs sources indépendantes.
DOCUMENTED_FALLBACK_BINANCE_FUTURES_MAKER_FEE_BPS = 2.0  # 0,02%
DOCUMENTED_FALLBACK_BINANCE_FUTURES_TAKER_FEE_BPS = 5.0  # 0,05%
