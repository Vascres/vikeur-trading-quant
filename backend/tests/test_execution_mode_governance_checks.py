"""Tests des GovernanceCheck en isolation (ADR-0004, ADR-0008) - miroir de
test_risk_engine.py pour les règles de gouvernance."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from execution_mode_governance.checks.capital_allocation_configured import CapitalAllocationConfiguredCheck
from execution_mode_governance.checks.exchange_api_operational import ExchangeApiOperationalCheck
from execution_mode_governance.checks.kill_switch_inactive import KillSwitchInactiveCheck
from execution_mode_governance.checks.live_eligible_strategy_exists import LiveEligibleStrategyExistsCheck
from execution_mode_governance.checks.minimum_duration import MinimumContinuousModeDurationCheck
from execution_mode_governance.checks.minimum_trade_count import MinimumTradeCountCheck
from execution_mode_governance.checks.non_negative_performance import NonNegativePerformanceCheck
from execution_mode_governance.checks.positive_exchange_balance import PositiveExchangeBalanceCheck
from execution_mode_governance.checks.recent_attestation import RecentAttestationCheck
from shared.governance_check import GovernanceContext


def _context(**overrides) -> GovernanceContext:
    base = dict(
        target_mode="real",
        current_mode="paper",
        evaluated_at=datetime.now(tz=UTC),
        continuous_mode_duration_seconds=40 * 86400,
        trade_count_since_mode_start=100,
        realized_pnl_since_mode_start=Decimal("50"),
        portfolio_snapshot_age_seconds=30.0,
        attestations={},
    )
    base.update(overrides)
    return GovernanceContext(**base)


# --- MinimumContinuousModeDurationCheck ---


def test_minimum_duration_passes_when_sufficient():
    result = MinimumContinuousModeDurationCheck(minimum_seconds=30 * 86400).check(_context())
    assert result.passed is True


def test_minimum_duration_fails_when_insufficient():
    result = MinimumContinuousModeDurationCheck(minimum_seconds=30 * 86400).check(
        _context(continuous_mode_duration_seconds=5 * 86400)
    )
    assert result.passed is False


# --- MinimumTradeCountCheck ---


def test_minimum_trade_count_passes_when_sufficient():
    result = MinimumTradeCountCheck(minimum_trade_count=50).check(_context(trade_count_since_mode_start=50))
    assert result.passed is True


def test_minimum_trade_count_fails_when_insufficient():
    result = MinimumTradeCountCheck(minimum_trade_count=50).check(_context(trade_count_since_mode_start=10))
    assert result.passed is False


# --- NonNegativePerformanceCheck ---


def test_non_negative_performance_passes_at_zero():
    result = NonNegativePerformanceCheck().check(_context(realized_pnl_since_mode_start=Decimal("0")))
    assert result.passed is True


def test_non_negative_performance_fails_when_negative():
    result = NonNegativePerformanceCheck().check(_context(realized_pnl_since_mode_start=Decimal("-1")))
    assert result.passed is False


# --- ExchangeApiOperationalCheck ---


def test_exchange_api_operational_fails_without_snapshot():
    result = ExchangeApiOperationalCheck().check(_context(portfolio_snapshot_age_seconds=None))
    assert result.passed is False


def test_exchange_api_operational_fails_when_stale():
    result = ExchangeApiOperationalCheck(max_snapshot_age_seconds=300).check(
        _context(portfolio_snapshot_age_seconds=1000.0)
    )
    assert result.passed is False


def test_exchange_api_operational_passes_when_fresh():
    result = ExchangeApiOperationalCheck(max_snapshot_age_seconds=300).check(
        _context(portfolio_snapshot_age_seconds=10.0)
    )
    assert result.passed is True


# --- RecentAttestationCheck ---


def test_recent_attestation_fails_when_never_attested():
    check = RecentAttestationCheck("kill_switch_tested", "Kill switch testé")
    result = check.check(_context(attestations={}))
    assert result.passed is False


def test_recent_attestation_fails_when_too_old():
    now = datetime.now(tz=UTC)
    check = RecentAttestationCheck("kill_switch_tested", "Kill switch testé", max_age_days=30)
    result = check.check(
        _context(evaluated_at=now, attestations={"kill_switch_tested": now - timedelta(days=40)})
    )
    assert result.passed is False


def test_recent_attestation_passes_when_fresh():
    now = datetime.now(tz=UTC)
    check = RecentAttestationCheck("kill_switch_tested", "Kill switch testé", max_age_days=30)
    result = check.check(
        _context(evaluated_at=now, attestations={"kill_switch_tested": now - timedelta(days=5)})
    )
    assert result.passed is True


# --- Étape 6 (16/08/2026) : "Mur de Fer" - 4 nouveaux prérequis ---


def test_kill_switch_inactive_passes_when_inactive():
    result = KillSwitchInactiveCheck().check(_context(kill_switch_active=False))
    assert result.passed is True


def test_kill_switch_inactive_fails_when_active():
    result = KillSwitchInactiveCheck().check(_context(kill_switch_active=True))
    assert result.passed is False


def test_kill_switch_inactive_fails_by_default():
    """Défaut sûr : un contexte qui ne renseigne jamais ce champ bloque,
    ne passe jamais silencieusement."""
    result = KillSwitchInactiveCheck().check(_context())
    assert result.passed is False


def test_capital_allocation_configured_passes_when_configured():
    result = CapitalAllocationConfiguredCheck().check(_context(capital_allocation_configured=True))
    assert result.passed is True


def test_capital_allocation_configured_fails_when_missing():
    result = CapitalAllocationConfiguredCheck().check(_context(capital_allocation_configured=False))
    assert result.passed is False


def test_capital_allocation_configured_fails_by_default():
    result = CapitalAllocationConfiguredCheck().check(_context())
    assert result.passed is False


def test_positive_exchange_balance_passes_when_positive():
    result = PositiveExchangeBalanceCheck().check(_context(exchange_balance_positive=True))
    assert result.passed is True


def test_positive_exchange_balance_fails_when_not_positive():
    result = PositiveExchangeBalanceCheck().check(_context(exchange_balance_positive=False))
    assert result.passed is False


def test_live_eligible_strategy_exists_passes_when_one_exists():
    result = LiveEligibleStrategyExistsCheck().check(_context(has_live_eligible_strategy=True))
    assert result.passed is True


def test_live_eligible_strategy_exists_fails_when_none_exists():
    """Le prérequis "crucial" du mandat, testé en isolation."""
    result = LiveEligibleStrategyExistsCheck().check(_context(has_live_eligible_strategy=False))
    assert result.passed is False
