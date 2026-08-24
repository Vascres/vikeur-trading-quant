"""Ajoute market_type à decisions et meta_decisions (chantier de routage
par market_type, 16/08/2026 - condition nécessaire pour que
LiquidationCascadeAgent, futures par nature, produise réellement des
décisions futures plutôt que d'être fondu dans le pipeline spot).

Nullable, AUCUNE valeur par défaut - c'est le point central de la
compatibilité ascendante de ce chantier : NULL signifie "non défini
explicitement", et `risk_engine` continue alors d'utiliser
`determine_market_type()` (ADR-0019, heuristique par position existante)
exactement comme avant ce chantier. Seules les décisions produites par
un groupe de moteurs 100% futures (aujourd'hui : liquidation_cascade
seul) reçoivent une valeur explicite ('futures_perpetual'), qui prend
alors le pas sur l'heuristique - jamais l'inverse, jamais un changement
de comportement pour les 3 moteurs directionnels spot déjà actifs.

Revision ID: 0026_decisions_market_type
Revises: 0025_liquidation_events
"""

from alembic import op

revision = "0026_decisions_market_type"
down_revision = "0025_liquidation_events"
branch_labels = None
depends_on = None

_MARKET_TYPE_CHECK = "market_type IN ('spot', 'futures_perpetual')"


def upgrade() -> None:
    op.execute(f"ALTER TABLE decisions ADD COLUMN market_type TEXT CHECK ({_MARKET_TYPE_CHECK});")
    op.execute(f"ALTER TABLE meta_decisions ADD COLUMN market_type TEXT CHECK ({_MARKET_TYPE_CHECK});")


def downgrade() -> None:
    op.execute("ALTER TABLE meta_decisions DROP COLUMN market_type;")
    op.execute("ALTER TABLE decisions DROP COLUMN market_type;")
