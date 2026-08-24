"""Ajoute `positions.decision_id` - sans cela, impossible d'attribuer une
position à la stratégie qui l'a ouverte (nécessaire pour comparer les
stratégies, Phase 17). Nullable : les positions de backtest restent
isolées dans backtest_trades (Phase 14, §3.1), non concernées ici.

Revision ID: 0006_add_position_decision_id
Revises: 0005_add_ml_models
Create Date: (Phase 17)
"""

from alembic import op

revision = "0006_add_position_decision_id"
down_revision = "0005_add_ml_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE positions ADD COLUMN decision_id BIGINT REFERENCES decisions(id);")
    op.execute("CREATE INDEX ix_positions_decision ON positions (decision_id);")


def downgrade() -> None:
    op.execute("ALTER TABLE positions DROP COLUMN decision_id;")
