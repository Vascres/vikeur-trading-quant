"""Calcul des métriques de cycle de vie à partir de trades clôturés (Étape
3 du plan validé le 16/08/2026). Fonctions pures : aucun accès DB, testées
en isolation - même exigence que `meta_engine/cost_estimation.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class TradeOutcome:
    """Un trade clôturé, tel que fourni par `strategy_lifecycle/repository.py`
    (jointure `positions` -> `decisions` -> éventuellement `meta_decisions`/
    `engine_opinions` pour une stratégie fusionnée)."""

    realized_pnl: Decimal  # devise de référence, peut être négatif
    entry_notional: Decimal  # entry_price * quantity, toujours > 0 si fourni


@dataclass(frozen=True)
class LifecycleMetrics:
    """Décomposition complète, jamais fusionnée en un seul verdict opaque
    (Principe 1 du mandat : "aucune boîte noire")."""

    ev_net_bps: float | None  # moyenne du P&L par trade, en bps du notionnel d'entrée
    cumulative_pnl: Decimal  # somme du P&L réalisé, devise de référence
    profit_factor: float | None  # gains bruts / |pertes brutes| - None si aucune perte
    sample_size: int


def compute_lifecycle_metrics(trades: list[TradeOutcome]) -> LifecycleMetrics:
    sample_size = len(trades)
    if sample_size == 0:
        return LifecycleMetrics(ev_net_bps=None, cumulative_pnl=Decimal(0), profit_factor=None, sample_size=0)

    bps_per_trade = [
        float(trade.realized_pnl / trade.entry_notional) * 10_000
        for trade in trades
        if trade.entry_notional > 0
    ]
    ev_net_bps = sum(bps_per_trade) / len(bps_per_trade) if bps_per_trade else None

    cumulative_pnl = sum((trade.realized_pnl for trade in trades), Decimal(0))

    gross_wins = sum((trade.realized_pnl for trade in trades if trade.realized_pnl > 0), Decimal(0))
    gross_losses = sum((-trade.realized_pnl for trade in trades if trade.realized_pnl < 0), Decimal(0))
    profit_factor = float(gross_wins / gross_losses) if gross_losses > 0 else None

    return LifecycleMetrics(
        ev_net_bps=ev_net_bps,
        cumulative_pnl=cumulative_pnl,
        profit_factor=profit_factor,
        sample_size=sample_size,
    )
