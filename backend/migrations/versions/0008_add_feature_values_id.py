"""Ajoute la colonne id manquante sur feature_values - nécessaire à la
traçabilité des décisions (Phase 4 §7, Phase 11).

Revision ID: 0008_add_feature_values_id
Revises: 0007_add_strategy_allocations
"""

from alembic import op

revision = "0008_add_feature_values_id"
down_revision = "0007_add_strategy_allocations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE feature_values ADD COLUMN id BIGSERIAL;")
    op.execute("CREATE INDEX ix_feature_values_id ON feature_values (id);")


def downgrade() -> None:
    op.execute("ALTER TABLE feature_values DROP COLUMN id;")
