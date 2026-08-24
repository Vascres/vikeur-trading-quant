"""Ajoute market_type, funding_bps, funding_source à positions (ADR-0018,
futures à exposition 1x) - additif, aucune ligne existante modifiée.
Toute position existante (spot) reçoit explicitement market_type='spot'.

Revision ID: 0016_add_futures_market_type
Revises: 0015_add_cost_model
"""

from alembic import op

revision = "0016_add_futures_market_type"
down_revision = "0015_add_cost_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE positions ADD COLUMN market_type TEXT "
        "NOT NULL DEFAULT 'spot' "
        "CHECK (market_type IN ('spot', 'futures_perpetual'));"
    )
    # Funding (ADR-0018 §3.4) : ne concerne que les positions futures -
    # NULL pour le spot, jamais une valeur inventée. `funding_source`
    # distingue explicitement une mesure réelle future ('measured_api',
    # chantier suivant, non implémenté par cette migration) d'un défaut
    # honnête ('non_mesure') - jamais confondu avec une mesure.
    op.execute("ALTER TABLE positions ADD COLUMN funding_bps DOUBLE PRECISION;")
    op.execute(
        "ALTER TABLE positions ADD COLUMN funding_source TEXT "
        "CHECK (funding_source IS NULL OR funding_source IN ('measured_api', 'non_mesure'));"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE positions DROP COLUMN funding_source;")
    op.execute("ALTER TABLE positions DROP COLUMN funding_bps;")
    op.execute("ALTER TABLE positions DROP COLUMN market_type;")
