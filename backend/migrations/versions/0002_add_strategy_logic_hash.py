"""Ajoute la colonne logic_hash manquante sur `strategies` (Phase 10, §4).

Revision ID: 0002_add_strategy_logic_hash
Revises: 0001_initial_schema
Create Date: (Phase 10)
"""

from alembic import op

revision = "0002_add_strategy_logic_hash"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Aucune ligne n'existe encore dans `strategies` à ce stade du projet
    # (aucun déploiement en production n'a eu lieu) - NOT NULL sans valeur
    # par défaut est donc sûr ici. Si cette migration est exécutée sur un
    # environnement contenant déjà des données, la commande échouera
    # explicitement plutôt que de corrompre silencieusement des lignes
    # existantes - comportement voulu.
    op.execute("ALTER TABLE strategies ADD COLUMN logic_hash TEXT NOT NULL;")


def downgrade() -> None:
    op.execute("ALTER TABLE strategies DROP COLUMN logic_hash;")
