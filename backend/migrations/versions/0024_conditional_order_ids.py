"""Ajoute stop_loss_order_id, take_profit_order_id à positions (triptyque
d'ordres, mandat §9, 16/08/2026).

Additif, ne concerne que le futures réel - NULL pour tout le spot et le
paper (même discipline que `leverage`/`margin_used`, migration 0023).

`take_profit_order_id` posé dès maintenant bien que la pose automatique
d'un take-profit ne soit pas encore câblée dans `execution_engine`
(mandat §9 : optionnel, nécessite un objectif de prix que les 3 moteurs
directionnels actifs ne fournissent pas encore) - schéma prêt, jamais
une seconde migration nécessaire le jour où un moteur en fournira un.

Revision ID: 0024_conditional_order_ids
Revises: 0023_futures_leverage_tracking
"""

from alembic import op

revision = "0024_conditional_order_ids"
down_revision = "0023_futures_leverage_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE positions ADD COLUMN stop_loss_order_id TEXT;")
    op.execute("ALTER TABLE positions ADD COLUMN take_profit_order_id TEXT;")


def downgrade() -> None:
    op.execute("ALTER TABLE positions DROP COLUMN take_profit_order_id;")
    op.execute("ALTER TABLE positions DROP COLUMN stop_loss_order_id;")
