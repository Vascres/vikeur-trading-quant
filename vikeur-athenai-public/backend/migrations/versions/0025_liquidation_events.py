"""Ajoute liquidation_events (chantier de données pour l'agent Liquidation
Cascade, 16/08/2026 - mandat, "moteur phare" si les données le confirment).

Première brique du chantier, délibérément scindée du reste : la donnée
avant le signal, le signal avant le moteur de décision (même discipline
que chaque autre chantier de ce projet - jamais tout construit d'un
bloc). Alimentée par `liquidation_ingest/main.py`, qui se connecte
directement au flux public Binance Futures (`<symbol>@forceOrder`,
aucune clé API requise - donnée de marché publique).

Limitation de la donnée elle-même (documentée par Binance, jamais
cachée) : ce flux ne pousse que la PLUS GROSSE liquidation par symbole
toutes les 1000ms - un échantillon, pas un décompte exhaustif. Pendant
une cascade réelle, le volume total liquidé est sous-compté par ce
flux. À prendre en compte lors de la calibration du signal de
détection (chantier suivant), jamais traité comme exhaustif.

Revision ID: 0025_liquidation_events
Revises: 0024_conditional_order_ids
"""

from alembic import op

revision = "0025_liquidation_events"
down_revision = "0024_conditional_order_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE liquidation_events (
            id              BIGSERIAL PRIMARY KEY,
            exchange        TEXT NOT NULL,
            symbol          TEXT NOT NULL,
            side            TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
            price           NUMERIC(20, 8) NOT NULL,
            quantity        NUMERIC(20, 8) NOT NULL,
            notional        NUMERIC(20, 8) NOT NULL,
            order_status    TEXT NOT NULL,
            event_time      TIMESTAMPTZ NOT NULL,
            received_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_liquidation_events_symbol_time ON liquidation_events (exchange, symbol, event_time DESC);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE liquidation_events;")
