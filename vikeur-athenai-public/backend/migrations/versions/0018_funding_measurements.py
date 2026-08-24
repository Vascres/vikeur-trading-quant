"""Ajoute funding_rate_measurements (ADR-0020) - mesure réelle du taux de financement
HTX Futures, même patron que fee_schedule (ADR-0016) : une ligne par
(exchange, symbol), toujours la dernière mesure (UPSERT côté
cost_model/main.py).

Nommage : PAS `funding_rates` - une table de ce nom existe déjà depuis
le schéma initial (`0001_initial_schema.py`), prévue à l'origine pour
une collecte en flux continu (colonnes `time`/`rate`, jamais alimentée
à ce jour) - découvert au déploiement (collision détectée par
`DuplicateTable` en production, jamais reproduite en local faute de
schéma initial complet dans le bac à sable de développement). Cette
table préexistante n'est pas touchée par cette migration.

Identifiant de révision volontairement raccourci (`0018_funding_measurements`,
pas `0018_add_funding_rate_measurements`) - `alembic_version.version_num`
est limité à VARCHAR(32) (déjà découvert une fois lors du déploiement
initial du projet) ; le nom de la table lui-même n'a pas cette
contrainte, seul l'identifiant de révision y est soumis.

Différence assumée avec fee_schedule (ADR-0016) : il n'existe aucun
repli documenté sensé pour le funding (contrairement au tarif de base
publié pour les frais) - un funding peut être positif ou négatif sans
qu'aucune valeur par défaut ne soit jamais "prudente". En cas d'échec
de mesure, aucune ligne n'est insérée pour ce cycle plutôt que
d'inventer une valeur - `source` ne prend donc en pratique que la
valeur 'measured_api'.

Revision ID: 0018_funding_measurements
Revises: 0017_add_position_side
"""

from alembic import op

revision = "0018_funding_measurements"
down_revision = "0017_add_position_side"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE funding_rate_measurements (
            id BIGSERIAL PRIMARY KEY,
            exchange TEXT NOT NULL,
            symbol TEXT NOT NULL,
            funding_rate_bps DOUBLE PRECISION NOT NULL,
            source TEXT NOT NULL CHECK (source = 'measured_api'),
            measured_at TIMESTAMPTZ NOT NULL,
            UNIQUE (exchange, symbol)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE funding_rate_measurements;")
