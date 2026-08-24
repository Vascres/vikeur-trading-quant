"""Ajoute pair_decisions, pair_incidents, decisions.pair_decision_id
(ADR-0021, Pair Execution Engine) - additif, aucune ligne existante
modifiée, `pair_decision_id` NULL pour toute décision existante
(aucune n'était une paire spot/futures couplée).

Revision ID: 0019_pair_execution
Revises: 0018_funding_measurements
"""

from alembic import op

revision = "0019_pair_execution"
down_revision = "0018_funding_measurements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE pair_decisions (
            id BIGSERIAL PRIMARY KEY,
            exchange TEXT NOT NULL,
            symbol TEXT NOT NULL,
            funding_rate_bps DOUBLE PRECISION NOT NULL,
            gross_edge_bps DOUBLE PRECISION NOT NULL,
            fees_bps DOUBLE PRECISION NOT NULL,
            slippage_bps DOUBLE PRECISION NOT NULL,
            net_edge_bps DOUBLE PRECISION NOT NULL,
            execution_probability DOUBLE PRECISION NOT NULL,
            execution_risk TEXT NOT NULL CHECK (execution_risk IN ('low', 'medium', 'high')),
            pair_quality_score DOUBLE PRECISION NOT NULL,
            decision TEXT NOT NULL CHECK (decision IN ('accept', 'reject')),
            status TEXT NOT NULL CHECK (status IN (
                'pending_validation', 'validated', 'executing',
                'both_filled', 'both_rejected', 'partial_execution',
                'completing_missing_leg', 'compensating', 'resolved'
            )),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            resolved_at TIMESTAMPTZ
        );
        """
    )

    # Relie chaque jambe (déjà représentée comme une décision classique,
    # réutilise tout le pipeline risk_engine/execution_engine existant
    # sans modification) à la paire dont elle fait partie.
    op.execute("ALTER TABLE decisions ADD COLUMN pair_decision_id BIGINT REFERENCES pair_decisions(id);")

    op.execute(
        """
        CREATE TABLE pair_incidents (
            id BIGSERIAL PRIMARY KEY,
            pair_decision_id BIGINT NOT NULL REFERENCES pair_decisions(id),
            incident_type TEXT NOT NULL CHECK (
                incident_type IN ('partial_execution', 'completion_failed', 'compensation_failed')
            ),
            filled_leg TEXT NOT NULL CHECK (filled_leg IN ('spot', 'futures_perpetual')),
            missing_leg TEXT NOT NULL CHECK (missing_leg IN ('spot', 'futures_perpetual')),
            residual_exposure_notional DOUBLE PRECISION NOT NULL,
            resolution_action TEXT NOT NULL CHECK (
                resolution_action IN ('completed_missing_leg', 'compensated_open_leg', 'unresolved')
            ),
            realized_cost_bps DOUBLE PRECISION,
            detected_at TIMESTAMPTZ NOT NULL,
            resolved_at TIMESTAMPTZ
        );
        """
    )
    op.execute("CREATE INDEX idx_pair_incidents_pair_decision_id ON pair_incidents (pair_decision_id);")


def downgrade() -> None:
    op.execute("DROP TABLE pair_incidents;")
    op.execute("ALTER TABLE decisions DROP COLUMN pair_decision_id;")
    op.execute("DROP TABLE pair_decisions;")
