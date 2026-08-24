"""Ajoute portfolio_snapshots et portfolio_snapshot_balances - remplace
STARTING_CAPITAL comme source du capital disponible (ADR-0003, ADR-0007).

Revision ID: 0009_add_portfolio_snapshots
Revises: 0008_add_feature_values_id
"""

from alembic import op

revision = "0009_add_portfolio_snapshots"
down_revision = "0008_add_feature_values_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE portfolio_snapshots (
            id                              BIGSERIAL PRIMARY KEY,
            exchange                        TEXT NOT NULL,
            taken_at                        TIMESTAMPTZ NOT NULL,
            reference_currency              TEXT NOT NULL DEFAULT 'USDT',
            total_value_reference_currency  NUMERIC NOT NULL,
            created_at                      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_portfolio_snapshots_exchange_taken_at "
        "ON portfolio_snapshots (exchange, taken_at DESC);"
    )

    op.execute(
        """
        CREATE TABLE portfolio_snapshot_balances (
            id                       BIGSERIAL PRIMARY KEY,
            portfolio_snapshot_id    BIGINT NOT NULL REFERENCES portfolio_snapshots (id),
            asset                    TEXT NOT NULL,
            amount                   NUMERIC NOT NULL
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_portfolio_snapshot_balances_snapshot_id "
        "ON portfolio_snapshot_balances (portfolio_snapshot_id);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE portfolio_snapshot_balances;")
    op.execute("DROP TABLE portfolio_snapshots;")
