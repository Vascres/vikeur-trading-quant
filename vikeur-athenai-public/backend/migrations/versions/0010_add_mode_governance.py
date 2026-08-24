"""Ajoute execution_mode_state et governance_attestations - remplace
EXECUTION_MODE comme variable d'environnement (ADR-0004, ADR-0008).

Revision ID: 0010_add_mode_governance
Revises: 0009_add_portfolio_snapshots
"""

from alembic import op

revision = "0010_add_mode_governance"
down_revision = "0009_add_portfolio_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE execution_mode_state (
            id                              BIGSERIAL PRIMARY KEY,
            mode                            TEXT NOT NULL,
            previous_mode                   TEXT,
            changed_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
            authorized_by                   TEXT NOT NULL,
            confirmation_phrase_provided    BOOLEAN NOT NULL DEFAULT FALSE,
            governance_snapshot             JSONB
        );
        """
    )
    op.execute("CREATE INDEX ix_execution_mode_state_changed_at ON execution_mode_state (changed_at DESC);")

    # État initial (ADR-0008) : reprend le comportement par défaut déjà en
    # place (EXECUTION_MODE=paper) pour ne jamais laisser le système sans
    # mode connu après cette migration - seule ligne jamais insérée sans
    # passer par request_mode_change(), et seule exception documentée au
    # principe "toujours un acte humain gouverné" (c'est une reprise de
    # l'état existant, pas une nouvelle décision).
    op.execute(
        """
        INSERT INTO execution_mode_state (mode, previous_mode, authorized_by, confirmation_phrase_provided)
        VALUES ('paper', NULL, 'migration_0010_seed', FALSE);
        """
    )

    op.execute(
        """
        CREATE TABLE governance_attestations (
            id             BIGSERIAL PRIMARY KEY,
            key            TEXT NOT NULL,
            attested_by    TEXT NOT NULL,
            attested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            notes          TEXT
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_governance_attestations_key_attested_at "
        "ON governance_attestations (key, attested_at DESC);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE governance_attestations;")
    op.execute("DROP TABLE execution_mode_state;")
