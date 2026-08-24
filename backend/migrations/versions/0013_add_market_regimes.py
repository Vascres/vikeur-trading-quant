"""Ajoute market_regimes - détection de régime de marché (ADR-0011).

Revision ID: 0013_add_market_regimes
Revises: 0012_add_meta_decisions
"""

from alembic import op

revision = "0013_add_market_regimes"
down_revision = "0012_add_meta_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE market_regimes (
            id                  BIGSERIAL PRIMARY KEY,
            exchange            TEXT NOT NULL,
            symbol              TEXT NOT NULL,
            time                TIMESTAMPTZ NOT NULL DEFAULT now(),
            regime_type         TEXT NOT NULL,
            confidence          DOUBLE PRECISION NOT NULL,
            trend               TEXT NOT NULL,
            volatility_level    TEXT NOT NULL
        );
        """
    )
    op.execute("CREATE INDEX ix_market_regimes_symbol_time ON market_regimes (symbol, time DESC);")


def downgrade() -> None:
    op.execute("DROP TABLE market_regimes;")
