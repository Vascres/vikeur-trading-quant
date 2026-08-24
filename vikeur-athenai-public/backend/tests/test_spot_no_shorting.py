from decimal import Decimal

from risk_engine.rules.spot_no_shorting import SpotNoShortingRule
from shared.risk_rule import RiskContext
from shared.strategy import Side


def _context(**overrides) -> RiskContext:
    base = dict(
        decision_id=1,
        exchange="htx",
        symbol="BTC/USDT",
        suggested_side=Side.BUY,
        success_probability=0.6,
        expected_value=0.01,
        risk_reward_ratio=2.0,
        available_capital=Decimal("1000"),
        current_price=Decimal("60000"),
        current_exposure_notional=Decimal("0"),
        daily_realized_pnl=Decimal("0"),
        consecutive_losses=0,
        open_position_quantity=Decimal("0"),
    )
    base.update(overrides)
    return RiskContext(**base)


def test_buy_always_passes_regardless_of_open_position():
    result = SpotNoShortingRule().check(
        _context(suggested_side=Side.BUY, open_position_quantity=Decimal("0"))
    )
    assert result.passed is True


def test_sell_without_open_position_is_rejected():
    result = SpotNoShortingRule().check(
        _context(suggested_side=Side.SELL, open_position_quantity=Decimal("0"))
    )
    assert result.passed is False


def test_sell_with_open_position_is_allowed():
    result = SpotNoShortingRule().check(
        _context(suggested_side=Side.SELL, open_position_quantity=Decimal("0.01"))
    )
    assert result.passed is True


# --- ADR-0018 : gate par market_type ---


def test_futures_sell_without_open_position_is_not_blocked_by_this_rule():
    """Le futures est gouverné par FuturesNotionalExposureCapRule, jamais
    par cette règle (ADR-0018 §3.2, une règle = une responsabilité)."""
    result = SpotNoShortingRule().check(
        _context(
            suggested_side=Side.SELL,
            open_position_quantity=Decimal("0"),
            market_type="futures_perpetual",
        )
    )
    assert result.passed is True


def test_default_market_type_is_spot():
    context = _context()
    assert context.market_type == "spot"
