"""Ajoute `funding_impact_bps` à `cost_estimates` (chantier CostModel
unique, 16/08/2026) - rend visible séparément l'impact du funding dans
la traçabilité des coûts d'une décision, plutôt que fusionné dans
`net_margin_bps` sans explication (Principe 1 : "aucune boîte noire").

Colonne additive, `NOT NULL DEFAULT 0` : aucun moteur actif ne fournit
encore de funding, le comportement observé pour les décisions déjà
persistées et pour tout nouvel appelant qui n'en fournit pas reste
inchangé (0 = aucun impact).

Revision ID: 0020_funding_impact_bps
Revises: 0019_pair_execution
"""

from alembic import op

revision = "0020_funding_impact_bps"
down_revision = "0019_pair_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cost_estimates ADD COLUMN funding_impact_bps DOUBLE PRECISION NOT NULL DEFAULT 0;"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cost_estimates DROP COLUMN funding_impact_bps;")
