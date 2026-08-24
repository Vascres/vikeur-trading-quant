"""Ajoute la colonne suggested_side manquante sur `decisions` (Phase 13).

Sans cette colonne, le Moteur de risque ne peut pas savoir si une décision
correspond à un achat ou une vente - un oubli du même type que celui
corrigé en Phase 10 (`strategies.logic_hash`), corrigé ici avant qu'il
ne cause une exécution dans le mauvais sens.

Revision ID: 0003_add_decision_side
Revises: 0002_add_strategy_logic_hash
Create Date: (Phase 13)
"""

from alembic import op

revision = "0003_add_decision_side"
down_revision = "0002_add_strategy_logic_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Aucune ligne n'existe encore dans `decisions` à ce stade du projet -
    # NOT NULL sans valeur par défaut est sûr ici (même raisonnement que
    # la migration 0002).
    op.execute(
        "ALTER TABLE decisions ADD COLUMN suggested_side TEXT NOT NULL CHECK (suggested_side IN ('buy', 'sell'));"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE decisions DROP COLUMN suggested_side;")
