"""Registre central des exchanges actifs (ADR-0012).

Remplace les constantes `EXCHANGE = "htx"` dispersées dans
`data_collector`, `data_normalizer`, `feature_engine`, `decision_engine`,
`portfolio`, `execution_mode_governance`. Ajouter un exchange = l'ajouter
à `ACTIVE_EXCHANGES` (variable d'environnement) après avoir écrit son
adaptateur (`data_collector/adapters/`) et son fournisseur de portefeuille
(`portfolio/`) - jamais en modifiant un service existant.
"""

from __future__ import annotations

import os

ACTIVE_EXCHANGES: list[str] = [
    name.strip() for name in os.environ.get("ACTIVE_EXCHANGES", "htx").split(",") if name.strip()
]


def get_exchange_credentials(exchange: str) -> tuple[str | None, str | None]:
    """Clés API nommées par exchange (`HTX_API_KEY`, `BINANCE_API_KEY`...) -
    jamais une paire générique `EXCHANGE_API_KEY` ambiguë dès qu'il y a
    plus d'un exchange actif (ADR-0012)."""
    prefix = exchange.upper()
    return os.environ.get(f"{prefix}_API_KEY"), os.environ.get(f"{prefix}_API_SECRET")


def get_futures_exchange_credentials(exchange: str) -> tuple[str | None, str | None]:
    """Clés API futures, délibérément distinctes des clés spot
    (ADR-0018/0019) - un compte de marge futures est un compte séparé
    sur la plupart des exchanges, jamais les mêmes permissions que le
    spot (`HTX_FUTURES_API_KEY`, pas `HTX_API_KEY`)."""
    prefix = exchange.upper()
    return os.environ.get(f"{prefix}_FUTURES_API_KEY"), os.environ.get(f"{prefix}_FUTURES_API_SECRET")
