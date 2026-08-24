"""Ajoute `backtest_trades` - isole les données simulées des tables live
(Phase 14, §3.1), sans toucher decisions/risk_checks/orders/positions.

Revision ID: 0004_add_backtest_trades
Revises: 0003_add_decision_side
Create Date: (Phase 14)
"""

from alembic import op

revision = "0004_add_backtest_trades"
down_revision = "0003_add_decision_side"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE backtest_trades (
            id                  BIGSERIAL PRIMARY KEY,
            backtest_run_id     BIGINT NOT NULL REFERENCES backtest_runs(id),
            symbol              TEXT NOT NULL,
            side                TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
            entry_time          TIMESTAMPTZ NOT NULL,
            exit_time           TIMESTAMPTZ NOT NULL,
            entry_price         NUMERIC(20, 8) NOT NULL,
            exit_price          NUMERIC(20, 8) NOT NULL,
            quantity            NUMERIC(20, 8) NOT NULL,
            pnl                 NUMERIC(20, 8) NOT NULL
        );
        """
    )
    op.execute("CREATE INDEX ix_backtest_trades_run ON backtest_trades (backtest_run_id);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS backtest_trades CASCADE;")
