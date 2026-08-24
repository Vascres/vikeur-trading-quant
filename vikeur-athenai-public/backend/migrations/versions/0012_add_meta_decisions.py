"""Ajoute engine_opinions et meta_decisions, fait évoluer `decisions` de
façon additive (ADR-0010) - strategy_id devient nullable, nouvelle
colonne meta_decision_id. Aucune ligne existante n'est modifiée.

Revision ID: 0012_add_meta_decisions
Revises: 0011_add_calibration_runs
"""

from alembic import op

revision = "0012_add_meta_decisions"
down_revision = "0011_add_calibration_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE engine_opinions (
            id                  BIGSERIAL PRIMARY KEY,
            strategy_id         BIGINT NOT NULL REFERENCES strategies(id),
            exchange            TEXT NOT NULL,
            symbol              TEXT NOT NULL,
            time                TIMESTAMPTZ NOT NULL DEFAULT now(),
            suggested_side      TEXT NOT NULL CHECK (suggested_side IN ('buy', 'sell')),
            score               DOUBLE PRECISION NOT NULL,
            confidence          DOUBLE PRECISION NOT NULL,
            uncertainty         DOUBLE PRECISION NOT NULL,
            rationale           JSONB NOT NULL DEFAULT '{}'::jsonb
        );
        """
    )
    op.execute("CREATE INDEX ix_engine_opinions_symbol_time ON engine_opinions (symbol, time DESC);")

    op.execute(
        """
        CREATE TABLE meta_decisions (
            id                          BIGSERIAL PRIMARY KEY,
            exchange                    TEXT NOT NULL,
            symbol                      TEXT NOT NULL,
            time                        TIMESTAMPTZ NOT NULL DEFAULT now(),
            fusion_method               TEXT NOT NULL,
            fused_score                 DOUBLE PRECISION,
            suggested_side              TEXT CHECK (suggested_side IN ('buy', 'sell')),
            weights_applied             JSONB NOT NULL DEFAULT '{}'::jsonb,
            contributing_opinion_ids    BIGINT[] NOT NULL DEFAULT '{}',
            calibration_run_id          BIGINT REFERENCES calibration_runs(id),
            success_probability         DOUBLE PRECISION,
            verdict                     TEXT NOT NULL CHECK (verdict IN ('signal', 'no_signal', 'insufficient_calibration'))
        );
        """
    )
    op.execute("CREATE INDEX ix_meta_decisions_symbol_time ON meta_decisions (symbol, time DESC);")

    # Évolution additive de `decisions` (ADR-0010) - une décision peut
    # désormais provenir d'une fusion multi-moteurs plutôt que d'un
    # unique `strategy_id`. Aucune ligne existante n'est modifiée : les
    # lignes historiques gardent `strategy_id` non nul et
    # `meta_decision_id` nul ; les nouvelles lignes ont l'inverse.
    op.execute("ALTER TABLE decisions ALTER COLUMN strategy_id DROP NOT NULL;")
    op.execute("ALTER TABLE decisions ADD COLUMN meta_decision_id BIGINT REFERENCES meta_decisions(id);")
    op.execute(
        "ALTER TABLE decisions ADD CONSTRAINT decisions_strategy_or_meta_chk "
        "CHECK (strategy_id IS NOT NULL OR meta_decision_id IS NOT NULL);"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE decisions DROP CONSTRAINT decisions_strategy_or_meta_chk;")
    op.execute("ALTER TABLE decisions DROP COLUMN meta_decision_id;")
    op.execute("ALTER TABLE decisions ALTER COLUMN strategy_id SET NOT NULL;")
    op.execute("DROP TABLE meta_decisions;")
    op.execute("DROP TABLE engine_opinions;")
