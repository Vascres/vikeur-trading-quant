"""Ajoute calibration_runs - couche de calibration probabiliste
(ADR-0009).

Revision ID: 0011_add_calibration_runs
Revises: 0010_add_mode_governance
"""

from alembic import op

revision = "0011_add_calibration_runs"
down_revision = "0010_add_mode_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE calibration_runs (
            id                       BIGSERIAL PRIMARY KEY,
            method                   TEXT NOT NULL,
            computed_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            training_period_start    TIMESTAMPTZ,
            training_period_end      TIMESTAMPTZ,
            sample_size              INTEGER NOT NULL,
            brier_score              DOUBLE PRECISION,
            is_validated             BOOLEAN NOT NULL,
            is_active                BOOLEAN NOT NULL DEFAULT FALSE,
            parameters               JSONB NOT NULL DEFAULT '{}'::jsonb,
            reason                   TEXT
        );
        """
    )
    op.execute("CREATE INDEX ix_calibration_runs_computed_at ON calibration_runs (computed_at DESC);")
    # Au plus une calibration active à la fois (ADR-0009) - contrainte
    # partielle plutôt qu'une colonne booléenne non vérifiée.
    op.execute(
        "CREATE UNIQUE INDEX ux_calibration_runs_single_active "
        "ON calibration_runs ((is_active)) WHERE is_active;"
    )


def downgrade() -> None:
    op.execute("DROP TABLE calibration_runs;")
