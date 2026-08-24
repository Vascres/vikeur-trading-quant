"""Ajoute fee_schedule (frais réels mesurés par exchange/symbole, ADR-0016)
et cost_estimates (traçabilité de la chaîne edge brut -> frais mesurés ->
marge nette, par décision) - tables additives, aucune ligne existante
modifiée.

Revision ID: 0015_add_cost_model
Revises: 0014_add_confidence_lifecycle
"""

from alembic import op

revision = "0015_add_cost_model"
down_revision = "0014_add_confidence_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE fee_schedule (
            id BIGSERIAL PRIMARY KEY,
            exchange TEXT NOT NULL,
            symbol TEXT NOT NULL,
            maker_fee_bps DOUBLE PRECISION NOT NULL,
            taker_fee_bps DOUBLE PRECISION NOT NULL,
            source TEXT NOT NULL CHECK (source IN ('measured_api', 'documented_fallback')),
            measured_at TIMESTAMPTZ NOT NULL,
            UNIQUE (exchange, symbol)
        );
        """
    )
    # Une seule ligne par (exchange, symbol) - toujours la dernière mesure
    # (UPSERT côté cost_model/main.py) : l'historique des mesures passées
    # n'est volontairement pas conservé ligne par ligne ici (un palier de
    # frais n'a pas la même valeur d'audit qu'une décision de trading) -
    # à revoir si un futur besoin de suivi historique des frais apparaît.

    op.execute(
        """
        CREATE TABLE cost_estimates (
            id BIGSERIAL PRIMARY KEY,
            decision_id BIGINT NOT NULL REFERENCES decisions(id),
            raw_edge_bps DOUBLE PRECISION,
            fee_bps DOUBLE PRECISION NOT NULL,
            net_margin_bps DOUBLE PRECISION,
            cleared_costs BOOLEAN NOT NULL,
            fee_source TEXT NOT NULL CHECK (fee_source IN ('measured_api', 'documented_fallback')),
            computed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX idx_cost_estimates_decision_id ON cost_estimates (decision_id);")


def downgrade() -> None:
    op.execute("DROP TABLE cost_estimates;")
    op.execute("DROP TABLE fee_schedule;")
