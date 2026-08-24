"""Ajoute market_type à portfolio_snapshots (17/08/2026 - solde de marge
Binance Futures dans la Live Vault, trou fonctionnel découvert en
répondant à une demande frontend : aucun adaptateur futures n'avait
jamais eu de méthode de solde, `portfolio/main.py` ne construisait des
fournisseurs que pour les exchanges spot).

Nullable, sans valeur par défaut - même discipline de compatibilité
ascendante que `decisions.market_type` (migration 0026) : NULL signifie
"solde spot" (comportement historique, chaque instantané existant l'est
implicitement), une valeur explicite ('futures_perpetual') ne concerne
que les nouveaux instantanés de marge futures.

IMPORTANT, découvert en auditant tous les lecteurs de cette table avant
d'y toucher : cinq endroits distincts (`risk_engine.
_fetch_real_available_capital`, `pair_execution._fetch_available_
capital`, `execution_mode_governance._build_governance_context`,
`strategy_lifecycle.repository.fetch_reference_capital`, et le calcul de
réconciliation dans `portfolio/main.py` lui-même) lisaient "le dernier
instantané pour cet exchange" SANS filtre de marché - une fois des
instantanés futures insérés dans la même table, chacun aurait pu
silencieusement récupérer un solde de marge futures à la place du solde
spot pour dimensionner une position SPOT. Les cinq ont été corrigés dans
le même chantier que cette migration, jamais après coup.

Revision ID: 0027_portfolio_market_type
Revises: 0026_decisions_market_type
"""

from alembic import op

revision = "0027_portfolio_market_type"
down_revision = "0026_decisions_market_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE portfolio_snapshots ADD COLUMN market_type TEXT "
        "CHECK (market_type IN ('spot', 'futures_perpetual'));"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE portfolio_snapshots DROP COLUMN market_type;")
