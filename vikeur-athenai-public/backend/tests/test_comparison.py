from paper_trading.comparison import _build_equity_curve


def test_equity_curve_starts_at_zero_by_default():
    curve = _build_equity_curve([10, -5, 20])
    assert curve == [0.0, 10.0, 5.0, 25.0]


def test_equity_curve_empty_trades_returns_starting_value_only():
    assert _build_equity_curve([]) == [0.0]


def test_equity_curve_custom_starting_value():
    curve = _build_equity_curve([10, 10], starting_value=1000.0)
    assert curve == [1000.0, 1010.0, 1020.0]
