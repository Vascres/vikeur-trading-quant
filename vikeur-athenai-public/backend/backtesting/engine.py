"""Moteur de backtest (Phase 14 ; ADR-0010).

Réutilise réellement DecisionEngine.evaluate() (migré depuis Strategy par
ADR-0010), evaluate_verdict() (Phase 11), meta_engine.cost_estimation
(ADR-0010, partagé avec decision_engine - jamais dupliqué), et 4 des 6
règles de risque (Phase 13) - voir Phase 14, §3.2 pour la limitation
assumée sur la règle de liquidité.

Limitation assumée (ADR-0010) : le backtest évalue un moteur individuel
isolément, sans fusion ni calibration (qui supposent plusieurs moteurs
et un historique de trades réels) - il utilise directement le `score`
brut du moteur comme s'il s'agissait d'une probabilité, exactement comme
le fait `calibration/main.py` en interim (chantier 3) avant qu'un moteur
ne soit promu dans le pool de fusion live.

N'écrit JAMAIS dans decisions/risk_checks/orders/positions (tables live) -
uniquement dans backtest_runs/backtest_results/backtest_trades (Phase 14, §3.1).
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

import asyncpg

from backtesting import metrics
from backtesting.portfolio import BacktestPortfolio
from decision_engine.thresholds import evaluate_verdict
from execution_engine.modes.backtest import ASSUMED_FEE_BPS, ASSUMED_SLIPPAGE_BPS
from meta_engine.cost_estimation import estimate_expected_value, estimate_risk_reward_ratio
from risk_engine.rules.daily_loss_limit import DailyLossLimitRule
from risk_engine.rules.max_consecutive_loss import MaxConsecutiveLossRule
from risk_engine.rules.max_exposure import MaxExposureRule
from risk_engine.rules.position_sizing import PositionSizingRule
from shared.decision_engine import DecisionEngine, Side
from shared.risk_rule import RiskContext

# Règles réellement réutilisées du Moteur de risque (Phase 13) - la règle
# de liquidité est volontairement exclue ici (Phase 14, §3.2).
BACKTEST_RISK_RULES = [
    PositionSizingRule(),
    MaxExposureRule(),
    DailyLossLimitRule(),
    MaxConsecutiveLossRule(),
]


async def run_backtest(
    db_pool: asyncpg.Pool,
    strategy: DecisionEngine,
    strategy_id: int,
    symbols: list[str],
    exchange: str,
    period_start: datetime,
    period_end: datetime,
    starting_capital: Decimal,
    feature_definition_ids: dict[str, int],
) -> int:
    """Exécute un backtest complet, persiste les résultats, retourne l'id du run."""
    async with db_pool.acquire() as conn:
        backtest_run_id = await conn.fetchval(
            """
            INSERT INTO backtest_runs (strategy_id, period_start, period_end, parameters)
            VALUES ($1, $2, $3, $4)
            RETURNING id;
            """,
            strategy_id,
            period_start,
            period_end,
            json.dumps(getattr(strategy, "parameters", {})),
        )

    portfolio = BacktestPortfolio(starting_capital=starting_capital)

    for symbol in symbols:
        await _replay_symbol(
            db_pool, strategy, symbol, exchange, period_start, period_end, feature_definition_ids, portfolio
        )

    await _persist_results(db_pool, backtest_run_id, portfolio)
    return backtest_run_id


async def _replay_symbol(
    db_pool: asyncpg.Pool,
    strategy: DecisionEngine,
    symbol: str,
    exchange: str,
    period_start: datetime,
    period_end: datetime,
    feature_definition_ids: dict[str, int],
    portfolio: BacktestPortfolio,
) -> None:
    async with db_pool.acquire() as conn:
        candles = await conn.fetch(
            """
            SELECT bucket, close FROM ohlcv_candles_1m
            WHERE exchange = $1 AND symbol = $2 AND bucket BETWEEN $3 AND $4
            ORDER BY bucket ASC;
            """,
            exchange,
            symbol,
            period_start,
            period_end,
        )

    for candle in candles:
        candle_time = candle["bucket"]
        current_price = Decimal(str(candle["close"]))

        features = await _fetch_features_as_of(db_pool, exchange, symbol, candle_time, feature_definition_ids)
        if len(features) < len(feature_definition_ids):
            continue  # historique de features incomplet à cet instant - on passe (Phase 14, §3.3)

        opinion = strategy.evaluate(features)
        if opinion is None:
            continue

        # Limitation assumée (ADR-0010, cf. docstring de module) : le score
        # brut du moteur est utilisé directement comme probabilité pour ce
        # backtest isolé, en l'absence de calibration/fusion à ce stade.
        expected_value = estimate_expected_value(features)
        risk_reward_ratio = estimate_risk_reward_ratio(features)
        if expected_value is None or risk_reward_ratio is None:
            continue  # coûts non estimables à partir des features disponibles

        if evaluate_verdict(opinion.score, expected_value, risk_reward_ratio) != "signal":
            continue

        context = RiskContext(
            decision_id=0,  # non persisté en backtest (Phase 14, §3.1)
            exchange=exchange,
            symbol=symbol,
            suggested_side=opinion.suggested_side,
            success_probability=opinion.score,
            expected_value=expected_value,
            risk_reward_ratio=risk_reward_ratio,
            available_capital=portfolio.available_capital,
            current_price=current_price,
            current_exposure_notional=portfolio.current_exposure_notional({symbol: current_price}),
            daily_realized_pnl=portfolio.daily_realized_pnl(candle_time),
            consecutive_losses=portfolio.consecutive_losses,
            order_book_bids=[],
            order_book_asks=[],
            kill_switch_active=False,
        )

        if not all(rule.check(context).passed for rule in BACKTEST_RISK_RULES):
            continue

        _apply_fill(
            portfolio, symbol, candle_time, current_price, opinion.suggested_side, context.suggested_quantity
        )


def _apply_fill(
    portfolio: BacktestPortfolio,
    symbol: str,
    time,
    current_price: Decimal,
    side: Side,
    quantity: Decimal | None,
) -> None:
    if quantity is None or quantity <= 0:
        return

    cost_bps = ASSUMED_SLIPPAGE_BPS + ASSUMED_FEE_BPS
    direction = 1 if side == Side.BUY else -1
    filled_price = current_price * (1 + direction * cost_bps / Decimal(10_000))

    if side == Side.BUY:
        portfolio.open_or_add(symbol, time, filled_price, quantity)
    else:
        portfolio.close(symbol, time, filled_price, quantity)  # None si rien à vendre (spot long-only)


async def _fetch_features_as_of(
    db_pool: asyncpg.Pool, exchange: str, symbol: str, as_of: datetime, feature_definition_ids: dict[str, int]
) -> dict[str, float]:
    features: dict[str, float] = {}
    async with db_pool.acquire() as conn:
        for name, definition_id in feature_definition_ids.items():
            row = await conn.fetchrow(
                """
                SELECT value FROM feature_values
                WHERE feature_definition_id = $1 AND exchange = $2 AND symbol = $3 AND time <= $4
                ORDER BY time DESC
                LIMIT 1;
                """,
                definition_id,
                exchange,
                symbol,
                as_of,
            )
            if row is not None:
                features[name] = row["value"]
    return features


async def _persist_results(db_pool: asyncpg.Pool, backtest_run_id: int, portfolio: BacktestPortfolio) -> None:
    trade_pnls = [float(t.pnl) for t in portfolio.closed_trades]
    equity_curve = [float(portfolio.starting_capital)] + [float(e) for e in portfolio.equity_curve]
    returns = [
        (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
        for i in range(1, len(equity_curve))
        if equity_curve[i - 1] != 0
    ]

    async with db_pool.acquire() as conn:
        if portfolio.closed_trades:
            await conn.executemany(
                """
                INSERT INTO backtest_trades
                    (backtest_run_id, symbol, side, entry_time, exit_time, entry_price, exit_price, quantity, pnl)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9);
                """,
                [
                    (
                        backtest_run_id,
                        t.symbol,
                        t.side,
                        t.entry_time,
                        t.exit_time,
                        t.entry_price,
                        t.exit_price,
                        t.quantity,
                        t.pnl,
                    )
                    for t in portfolio.closed_trades
                ],
            )

        await conn.execute(
            """
            INSERT INTO backtest_results
                (backtest_run_id, sharpe_ratio, sortino_ratio, calmar_ratio, max_drawdown,
                 profit_factor, expectancy, ulcer_index, total_trades)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9);
            """,
            backtest_run_id,
            metrics.sharpe_ratio(returns),
            metrics.sortino_ratio(returns),
            metrics.calmar_ratio(equity_curve),
            metrics.max_drawdown(equity_curve),
            metrics.profit_factor(trade_pnls),
            metrics.expectancy(trade_pnls),
            metrics.ulcer_index(equity_curve),
            len(portfolio.closed_trades),
        )
