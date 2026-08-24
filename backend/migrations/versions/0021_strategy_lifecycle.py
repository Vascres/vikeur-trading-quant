"""Ajoute strategy_lifecycle_state et strategy_lifecycle_history (Étape 3
du plan validé le 16/08/2026 - "Strategy Lifecycle Manager").

Généralise le vocabulaire à 3 niveaux du Confidence Lifecycle (ADR-0015,
`shared/confidence_lifecycle.py`) à un second cas d'usage réel, comme
son propre docstring l'anticipait déjà - mais avec un vocabulaire dédié
(9 statuts, chemins de promotion ET d'éviction) plutôt qu'une réutilisation
forcée des 3 niveaux de maturité de calibration : la santé économique
d'une stratégie n'est pas un sous-cas de la maturité d'un échantillon de
calibration (elle peut régresser - DEGRADED, SUSPENDED - ce que le
Confidence Lifecycle ne prévoit jamais).

`strategy_lifecycle_state` : une ligne par stratégie, toujours la
dernière transition (source de vérité lue par `decision_engine`, en SQL
direct, jamais par import - même principe que `fee_schedule`).

`strategy_lifecycle_history` : append-only, jamais purgée (Règle
Absolue du mandat : "Ne jamais supprimer les données historiques d'une
stratégie suspendue" - conserve trades, décisions, performances,
raisons de chaque transition).

Revision ID: 0021_strategy_lifecycle
Revises: 0020_funding_impact_bps
"""

from alembic import op

revision = "0021_strategy_lifecycle"
down_revision = "0020_funding_impact_bps"
branch_labels = None
depends_on = None

_STATUS_CHECK = (
    "status IN ("
    "'registered', 'collecting', 'experimental', 'validated', 'production', "
    "'under_review', 'degraded', 'suspended', 'deprecated'"
    ")"
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE strategy_lifecycle_state (
            strategy_id                        BIGINT PRIMARY KEY REFERENCES strategies(id),
            status                              TEXT NOT NULL CHECK ({_STATUS_CHECK}),
            reason                               TEXT,
            ev_net_bps                          DOUBLE PRECISION,
            cumulative_pnl_reference_currency   NUMERIC(20, 8),
            profit_factor                       DOUBLE PRECISION,
            sample_size                         INTEGER NOT NULL DEFAULT 0,
            transitioned_at                     TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE strategy_lifecycle_history (
            id                                  BIGSERIAL PRIMARY KEY,
            strategy_id                         BIGINT NOT NULL REFERENCES strategies(id),
            previous_status                     TEXT,
            new_status                          TEXT NOT NULL CHECK (new_status IN (
                'registered', 'collecting', 'experimental', 'validated', 'production',
                'under_review', 'degraded', 'suspended', 'deprecated'
            )),
            reason                               TEXT NOT NULL,
            ev_net_bps                          DOUBLE PRECISION,
            cumulative_pnl_reference_currency   NUMERIC(20, 8),
            profit_factor                       DOUBLE PRECISION,
            sample_size                         INTEGER NOT NULL,
            transitioned_at                     TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_strategy_lifecycle_history_strategy ON strategy_lifecycle_history (strategy_id);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE strategy_lifecycle_history;")
    op.execute("DROP TABLE strategy_lifecycle_state;")
