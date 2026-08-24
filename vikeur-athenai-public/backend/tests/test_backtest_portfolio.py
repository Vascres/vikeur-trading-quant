"""Tests de la Phase 14 : logique pure du portefeuille simulé."""

from datetime import datetime
from decimal import Decimal

from backtesting.portfolio import BacktestPortfolio


def test_open_position_creates_new_entry():
    portfolio = BacktestPortfolio(starting_capital=Decimal("1000"))
    portfolio.open_or_add("BTC/USDT", datetime(2026, 1, 1), Decimal("60000"), Decimal("0.01"))

    position = portfolio.open_positions["BTC/USDT"]
    assert position.entry_price == Decimal("60000")
    assert position.quantity == Decimal("0.01")


def test_open_or_add_averages_price_correctly():
    portfolio = BacktestPortfolio(starting_capital=Decimal("1000"))
    portfolio.open_or_add("BTC/USDT", datetime(2026, 1, 1), Decimal("60000"), Decimal("0.01"))
    portfolio.open_or_add("BTC/USDT", datetime(2026, 1, 2), Decimal("62000"), Decimal("0.01"))

    position = portfolio.open_positions["BTC/USDT"]
    assert position.quantity == Decimal("0.02")
    assert position.entry_price == Decimal("61000")  # moyenne pondérée équitable ici


def test_close_without_open_position_returns_none_spot_long_only():
    portfolio = BacktestPortfolio(starting_capital=Decimal("1000"))
    result = portfolio.close("BTC/USDT", datetime(2026, 1, 1), Decimal("60000"), Decimal("0.01"))
    assert result is None


def test_close_computes_correct_pnl_and_updates_capital():
    portfolio = BacktestPortfolio(starting_capital=Decimal("1000"))
    portfolio.open_or_add("BTC/USDT", datetime(2026, 1, 1), Decimal("60000"), Decimal("0.01"))

    trade = portfolio.close("BTC/USDT", datetime(2026, 1, 2), Decimal("61000"), Decimal("0.01"))

    assert trade is not None
    assert trade.pnl == Decimal("10")  # (61000-60000)*0.01
    assert portfolio.realized_pnl == Decimal("10")
    assert portfolio.available_capital == Decimal("1010")
    assert "BTC/USDT" not in portfolio.open_positions  # position totalement fermée


def test_partial_close_keeps_remaining_position_open():
    portfolio = BacktestPortfolio(starting_capital=Decimal("1000"))
    portfolio.open_or_add("BTC/USDT", datetime(2026, 1, 1), Decimal("60000"), Decimal("0.02"))

    portfolio.close("BTC/USDT", datetime(2026, 1, 2), Decimal("61000"), Decimal("0.01"))

    remaining = portfolio.open_positions["BTC/USDT"]
    assert remaining.quantity == Decimal("0.01")
    assert remaining.entry_price == Decimal("60000")  # prix d'entrée inchangé sur le reliquat


def test_consecutive_losses_increments_on_loss_and_resets_on_win():
    portfolio = BacktestPortfolio(starting_capital=Decimal("1000"))

    portfolio.open_or_add("BTC/USDT", datetime(2026, 1, 1), Decimal("60000"), Decimal("0.01"))
    portfolio.close("BTC/USDT", datetime(2026, 1, 2), Decimal("59000"), Decimal("0.01"))  # perte
    assert portfolio.consecutive_losses == 1

    portfolio.open_or_add("BTC/USDT", datetime(2026, 1, 3), Decimal("59000"), Decimal("0.01"))
    portfolio.close("BTC/USDT", datetime(2026, 1, 4), Decimal("58000"), Decimal("0.01"))  # perte
    assert portfolio.consecutive_losses == 2

    portfolio.open_or_add("BTC/USDT", datetime(2026, 1, 5), Decimal("58000"), Decimal("0.01"))
    portfolio.close("BTC/USDT", datetime(2026, 1, 6), Decimal("59000"), Decimal("0.01"))  # gain
    assert portfolio.consecutive_losses == 0


def test_current_exposure_notional_sums_open_positions():
    portfolio = BacktestPortfolio(starting_capital=Decimal("1000"))
    portfolio.open_or_add("BTC/USDT", datetime(2026, 1, 1), Decimal("60000"), Decimal("0.01"))
    portfolio.open_or_add("ETH/USDT", datetime(2026, 1, 1), Decimal("3000"), Decimal("0.1"))

    exposure = portfolio.current_exposure_notional(
        {"BTC/USDT": Decimal("60000"), "ETH/USDT": Decimal("3000")}
    )
    assert exposure == Decimal("900")  # 600 + 300


def test_daily_realized_pnl_filters_by_day():
    portfolio = BacktestPortfolio(starting_capital=Decimal("1000"))
    portfolio.open_or_add("BTC/USDT", datetime(2026, 1, 1), Decimal("60000"), Decimal("0.01"))
    portfolio.close("BTC/USDT", datetime(2026, 1, 1, 15, 0), Decimal("61000"), Decimal("0.01"))

    portfolio.open_or_add("BTC/USDT", datetime(2026, 1, 2), Decimal("61000"), Decimal("0.01"))
    portfolio.close("BTC/USDT", datetime(2026, 1, 2, 10, 0), Decimal("60000"), Decimal("0.01"))

    assert portfolio.daily_realized_pnl(datetime(2026, 1, 1, 23, 0)) == Decimal("10")
    assert portfolio.daily_realized_pnl(datetime(2026, 1, 2, 23, 0)) == Decimal("-10")
