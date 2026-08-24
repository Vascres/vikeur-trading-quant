"""Ajoute `ml_models` (Phase 16, §5) - is_active reste FALSE en V1,
aucun code de cette phase ne l'active jamais.

Revision ID: 0005_add_ml_models
Revises: 0004_add_backtest_trades
Create Date: (Phase 16)
"""

from alembic import op

revision = "0005_add_ml_models"
down_revision = "0004_add_backtest_trades"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ml_models (
            id                  BIGSERIAL PRIMARY KEY,
            name                TEXT NOT NULL,
            version             INTEGER NOT NULL,
            algorithm           TEXT NOT NULL,
            trained_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            training_period_start TIMESTAMPTZ NOT NULL,
            training_period_end   TIMESTAMPTZ NOT NULL,
            metrics             JSONB NOT NULL,
            serialized_model    BYTEA NOT NULL,
            is_active           BOOLEAN NOT NULL DEFAULT false,
            UNIQUE (name, version)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ml_models CASCADE;")
