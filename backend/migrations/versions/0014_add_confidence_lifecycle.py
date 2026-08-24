"""Ajoute des colonnes additives à meta_decisions pour la gouvernance
maturité/mode (ADR-0014, ADR-0015) et l'explicabilité des décisions
(Decision Explainability) - aucune ligne existante modifiée, seulement
de nouvelles colonnes avec des valeurs par défaut sûres pour l'historique.

Revision ID: 0014_add_confidence_lifecycle
Revises: 0013_add_market_regimes
"""

from alembic import op

revision = "0014_add_confidence_lifecycle"
down_revision = "0013_add_market_regimes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `calibration_maturity` (ADR-0015, Confidence Lifecycle) : niveau de
    # maturité de la calibration utilisée pour cette décision. Les lignes
    # historiques (avant ce chantier) sont explicitement marquées
    # 'validated' quand une calibration était appliquée (comportement
    # d'alors, ADR-0009 : jamais autre chose que 'validated' n'était
    # possible) et 'collecting' sinon - jamais une valeur inventée, une
    # déduction directe du comportement du code à l'époque.
    op.execute(
        "ALTER TABLE meta_decisions ADD COLUMN calibration_maturity TEXT "
        "NOT NULL DEFAULT 'collecting' "
        "CHECK (calibration_maturity IN ('collecting', 'preliminary', 'validated'));"
    )
    op.execute(
        "UPDATE meta_decisions SET calibration_maturity = 'validated' "
        "WHERE success_probability IS NOT NULL;"
    )

    # `verdict_reason` (Decision Explainability) : explication en langage
    # humain du verdict - NULL pour l'historique (aucune reconstitution
    # fiable possible a posteriori, jamais une explication inventée,
    # principe directeur 1).
    op.execute("ALTER TABLE meta_decisions ADD COLUMN verdict_reason TEXT;")

    # `execution_mode` (ADR-0014) : mode d'exécution au moment de la
    # décision - toutes les décisions passées ont été prises alors que
    # seul le mode 'paper' existait en pratique (cf. passation de projet),
    # donc un défaut 'paper' pour l'historique est une déduction directe,
    # pas une invention.
    op.execute(
        "ALTER TABLE meta_decisions ADD COLUMN execution_mode TEXT "
        "NOT NULL DEFAULT 'paper' "
        "CHECK (execution_mode IN ('backtest', 'paper', 'real'));"
    )

    # `regime_type` / `regime_confidence` (Decision Explainability) :
    # duplique à dessein `market_regimes` (ADR-0011) au moment précis de
    # la décision plutôt que de forcer un rapprochement approximatif par
    # horodatage côté API - NULL pour l'historique antérieur à ADR-0011.
    op.execute("ALTER TABLE meta_decisions ADD COLUMN regime_type TEXT;")
    op.execute("ALTER TABLE meta_decisions ADD COLUMN regime_confidence DOUBLE PRECISION;")


def downgrade() -> None:
    op.execute("ALTER TABLE meta_decisions DROP COLUMN regime_confidence;")
    op.execute("ALTER TABLE meta_decisions DROP COLUMN regime_type;")
    op.execute("ALTER TABLE meta_decisions DROP COLUMN execution_mode;")
    op.execute("ALTER TABLE meta_decisions DROP COLUMN verdict_reason;")
    op.execute("ALTER TABLE meta_decisions DROP COLUMN calibration_maturity;")
