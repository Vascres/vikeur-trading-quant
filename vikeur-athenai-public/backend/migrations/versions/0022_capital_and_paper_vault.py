"""Ajoute capital_allocation_config (Étape 5 - Live Vault) et
paper_capital_config (Étape 4 - Paper Vault) - plan validé le 16/08/2026.

Corrige au passage un écart découvert en préparant ce chantier : jusqu'ici,
`risk_engine` lisait `available_capital` depuis `portfolio_snapshots`
(solde RÉEL de l'exchange) sans distinction de mode d'exécution - une
décision évaluée en mode PAPER dimensionnait donc sa position sur le
capital réel du compte, pas sur un capital virtuel indépendant. Ce n'est
pas la "séparation étanche" que le mandat demande (§7-9) ; ce chantier la
construit.

`capital_allocation_config` : le "mur d'allocation" - `risk_engine`
n'expose au mode réel qu'une fraction (`allocation_pct`) du solde réel
total, jamais le solde entier par défaut implicite. Une ligne par
exchange, historisée (jamais de mutation, même principe que
`execution_mode_state`) - seule la plus récente par exchange fait foi.

`paper_capital_config` : le capital virtuel du Paper Portfolio, totalement
indépendant du solde réel. Une seule ligne "active" à la fois (la plus
récente) - en poser une nouvelle réinitialise le capital de référence
sans jamais effacer l'historique des trades déjà simulés (Règle Absolue
du mandat).

Seedées toutes les deux avec des valeurs de repli documentées,
backward-compatibles : 100% d'allocation (comportement inchangé pour le
mode réel tant que personne ne choisit une valeur différente) et 1000
USDT de capital paper par défaut (exemple donné explicitement par le
mandat §8, modifiable ensuite via l'API).

Revision ID: 0022_capital_and_paper_vault
Revises: 0021_strategy_lifecycle
"""

from alembic import op

revision = "0022_capital_and_paper_vault"
down_revision = "0021_strategy_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE capital_allocation_config (
            id              BIGSERIAL PRIMARY KEY,
            exchange        TEXT NOT NULL,
            allocation_pct  NUMERIC(5, 2) NOT NULL CHECK (allocation_pct > 0 AND allocation_pct <= 100),
            set_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            set_by          TEXT
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_capital_allocation_config_exchange ON capital_allocation_config (exchange, set_at);"
    )
    op.execute(
        """
        INSERT INTO capital_allocation_config (exchange, allocation_pct, set_by)
        VALUES ('htx', 100.00, 'migration_default');
        """
    )

    op.execute(
        """
        CREATE TABLE paper_capital_config (
            id                  BIGSERIAL PRIMARY KEY,
            initial_capital     NUMERIC(20, 8) NOT NULL CHECK (initial_capital > 0),
            reference_currency  TEXT NOT NULL DEFAULT 'USDT',
            set_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            set_by              TEXT
        );
        """
    )
    op.execute(
        """
        INSERT INTO paper_capital_config (initial_capital, set_by)
        VALUES (1000.00, 'migration_default');
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE paper_capital_config;")
    op.execute("DROP TABLE capital_allocation_config;")
