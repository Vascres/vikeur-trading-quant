"""Ajoute market_type à paper_capital_config (18/08/2026 - deux pools de
capital Paper Trading séparés, spot et futures, chacun avec son propre
suivi de P&L réalisé indépendant).

Décision confirmée explicitement avec l'opérateur avant ce chantier :
un seul pool PAR market_type, PARTAGÉ entre tous les exchanges actifs -
jamais un pool par exchange (le paper trading suit désormais Binance en
priorité, mais rien n'empêche HTX de continuer à contribuer au même
pool spot).

Nullable, sans valeur par défaut - même discipline de compatibilité
ascendante que `decisions.market_type` (migration 0026) et
`portfolio_snapshots.market_type` (migration 0027) : NULL signifie
"pool spot" (comportement historique, la ligne existante - 350 USDT au
moment de l'écriture - le devient implicitement), une valeur explicite
('futures_perpetual') ne concerne que le nouveau pool futures.

Seedé avec un repli documenté (1000 USDT, même valeur que le seed
historique de la migration 0022) pour que le pool futures ne soit
jamais "non configuré" par défaut - modifiable ensuite via l'API/le
formulaire dédié, comme le pool spot.

Revision ID: 0028_paper_capital_market_type
Revises: 0027_portfolio_market_type
"""

from alembic import op

revision = "0028_paper_capital_market_type"
down_revision = "0027_portfolio_market_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE paper_capital_config ADD COLUMN market_type TEXT "
        "CHECK (market_type IN ('spot', 'futures_perpetual'));"
    )
    op.execute(
        """
        INSERT INTO paper_capital_config (initial_capital, set_by, market_type)
        VALUES (1000.00, 'migration_default', 'futures_perpetual');
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM paper_capital_config WHERE market_type = 'futures_perpetual';")
    op.execute("ALTER TABLE paper_capital_config DROP COLUMN market_type;")
