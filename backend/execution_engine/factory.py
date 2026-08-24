"""Sélection de l'implémentation du mode d'exécution (Phase 12, §4 ;
ADR-0004, ADR-0008).

Le mode lui-même n'est plus jamais lu ici depuis une variable
d'environnement - il est fourni par l'appelant, qui l'obtient via
`shared.execution_mode_state.get_current_mode` (source de vérité :
`execution_mode_state`, gouvernée par `execution_mode_governance`).
Cette fonction reste une fabrique pure : mode connu -> implémentation
correspondante, rien de plus.
"""

import asyncpg

from execution_engine.modes.backtest import BacktestExecutionMode
from execution_engine.modes.paper import PaperExecutionMode
from execution_engine.modes.real import RealExecutionMode
from shared.exchange_adapter import ExchangeAdapter
from shared.execution_mode import ExecutionMode
from shared.futures_adapter import FuturesExchangeAdapter

VALID_MODES = {"backtest", "paper", "real"}


def get_execution_mode(
    mode: str,
    db_pool: asyncpg.Pool,
    exchange_adapters: dict[str, ExchangeAdapter] | None = None,
    futures_exchange_adapters: dict[str, FuturesExchangeAdapter] | None = None,
    publish_journal_event=None,
) -> ExecutionMode:
    if mode not in VALID_MODES:
        raise ValueError(f"Mode d'exécution invalide : '{mode}'. Attendu : {VALID_MODES}.")

    if mode == "backtest":
        return BacktestExecutionMode(db_pool)
    if mode == "paper":
        return PaperExecutionMode(db_pool)

    # mode == "real"
    if not exchange_adapters:
        raise ValueError("Le mode 'real' nécessite au moins un ExchangeAdapter configuré (Phase 12, §5).")
    return RealExecutionMode(db_pool, exchange_adapters, futures_exchange_adapters, publish_journal_event)
