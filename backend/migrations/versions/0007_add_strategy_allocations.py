"""Ajoute `strategy_allocations` - recommandations calculées, jamais
appliquées automatiquement au dimensionnement réel (Phase 17, §3).

Revision ID: 0007_add_strategy_allocations
Revises: 0006_add_position_decision_id
Create Date: (Phase 17)
"""

from alembic import op

revision = "0007_add_strategy_allocations"
down_revision = "0006_add_position_decision_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE strategy_allocations (
            id                      BIGSERIAL PRIMARY KEY,
            strategy_id             BIGINT NOT NULL REFERENCES strategies(id),
            computed_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            recommended_fraction    DOUBLE PRECISION NOT NULL,
            based_on_trade_count    INTEGER NOT NULL,
            applied                 BOOLEAN NOT NULL DEFAULT false
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS strategy_allocations CASCADE;")
