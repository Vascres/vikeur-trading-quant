"""Ajoute position_side à positions (ADR-0019) - découvert nécessaire en
concevant le branchement réel du futures : contrairement au spot
(toujours long), une position futures peut être longue ou courte, et
les deux ne sont jamais fongibles avec une position spot sur le même
symbole (cf. ADR-0019 §2). Additif, NULL pour tout le spot existant et
futur (le sens reste implicite - toujours long - pour le spot, jamais
forcé pour ne rien changer à son comportement).

Revision ID: 0017_add_position_side
Revises: 0016_add_futures_market_type
"""

from alembic import op

revision = "0017_add_position_side"
down_revision = "0016_add_futures_market_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE positions ADD COLUMN position_side TEXT "
        "CHECK (position_side IS NULL OR position_side IN ('long', 'short'));"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE positions DROP COLUMN position_side;")
