"""Ajoute leverage, margin_used, liquidation_price_reference à positions
(décision CTO du 16/08/2026, Étapes 7-8 - plafond système à 2x, cf.
`shared/futures_margin.MAX_LEVERAGE`).

Additif, ne concerne que le futures - NULL pour tout le spot existant et
futur (même discipline que `market_type`/`funding_bps`, migration 0016).

`leverage` : levier réellement utilisé pour cette position (1 par défaut
tant que les adaptateurs n'envoient que `lever_rate=1`/`leverage=1` à
l'exchange - cf. docstring de `MAX_LEVERAGE`, l'activation réelle du
levier attend le filet de sécurité du "triptyque d'ordres").

`margin_used` : marge réellement engagée (notionnel / levier) - distincte
du notionnel de la position, jamais confondue (Principe 1 du mandat :
"aucune boîte noire" - la marge doit être visible séparément).

`liquidation_price_reference` : prix de liquidation calculé au moment de
l'ouverture (`shared.futures_margin.compute_liquidation_price`) -
référence pour la traçabilité et un futur stop-loss automatique, jamais
recalculé après coup silencieusement.

Revision ID: 0023_futures_leverage_tracking
Revises: 0022_capital_and_paper_vault
"""

from alembic import op

revision = "0023_futures_leverage_tracking"
down_revision = "0022_capital_and_paper_vault"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE positions ADD COLUMN leverage INTEGER;")
    op.execute("ALTER TABLE positions ADD COLUMN margin_used NUMERIC(20, 8);")
    op.execute("ALTER TABLE positions ADD COLUMN liquidation_price_reference NUMERIC(20, 8);")


def downgrade() -> None:
    op.execute("ALTER TABLE positions DROP COLUMN liquidation_price_reference;")
    op.execute("ALTER TABLE positions DROP COLUMN margin_used;")
    op.execute("ALTER TABLE positions DROP COLUMN leverage;")
