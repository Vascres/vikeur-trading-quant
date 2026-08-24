"""Schéma initial - conforme au modèle logique défini en Phase 4.

Revision ID: 0001_initial_schema
Revises:
Create Date: (Phase 6)
"""

from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")

    # ------------------------------------------------------------------
    # 1. Définitions versionnées (jamais modifiées après création - Phase 4 §5.2/5.3)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE feature_definitions (
            id              BIGSERIAL PRIMARY KEY,
            name            TEXT NOT NULL,
            version         INTEGER NOT NULL,
            description     TEXT NOT NULL,
            logic_hash      TEXT NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (name, version)
        );
        """
    )

    op.execute(
        """
        CREATE TABLE strategies (
            id              BIGSERIAL PRIMARY KEY,
            name            TEXT NOT NULL,
            version         INTEGER NOT NULL,
            parameters      JSONB NOT NULL,
            is_active       BOOLEAN NOT NULL DEFAULT false,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (name, version)
        );
        """
    )

    # ------------------------------------------------------------------
    # 2. Hypertables de marché (Phase 4 §5.1)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE raw_market_data (
            time            TIMESTAMPTZ NOT NULL,
            exchange        TEXT NOT NULL,
            symbol          TEXT NOT NULL,
            price           NUMERIC(20, 8) NOT NULL,
            quantity        NUMERIC(20, 8) NOT NULL,
            side            TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
            trade_id        TEXT,
            received_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "SELECT create_hypertable('raw_market_data', 'time', chunk_time_interval => INTERVAL '1 day');"
    )
    op.execute(
        "CREATE INDEX ix_raw_market_data_symbol_time ON raw_market_data (exchange, symbol, time DESC);"
    )

    op.execute(
        """
        CREATE TABLE order_book_snapshots (
            time            TIMESTAMPTZ NOT NULL,
            exchange        TEXT NOT NULL,
            symbol          TEXT NOT NULL,
            bids            JSONB NOT NULL,  -- [[prix, quantite], ...] top N niveaux
            asks            JSONB NOT NULL,
            received_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "SELECT create_hypertable('order_book_snapshots', 'time', chunk_time_interval => INTERVAL '1 day');"
    )
    op.execute(
        "CREATE INDEX ix_order_book_symbol_time ON order_book_snapshots (exchange, symbol, time DESC);"
    )

    op.execute(
        """
        CREATE TABLE funding_rates (
            time            TIMESTAMPTZ NOT NULL,
            exchange        TEXT NOT NULL,
            symbol          TEXT NOT NULL,
            rate            NUMERIC(12, 8) NOT NULL
        );
        """
    )
    op.execute(
        "SELECT create_hypertable('funding_rates', 'time', chunk_time_interval => INTERVAL '30 days');"
    )

    op.execute(
        """
        CREATE TABLE feature_values (
            time                    TIMESTAMPTZ NOT NULL,
            feature_definition_id   BIGINT NOT NULL REFERENCES feature_definitions(id),
            exchange                TEXT NOT NULL,
            symbol                  TEXT NOT NULL,
            value                   DOUBLE PRECISION NOT NULL
        );
        """
    )
    op.execute("SELECT create_hypertable('feature_values', 'time', chunk_time_interval => INTERVAL '1 day');")
    op.execute(
        "CREATE INDEX ix_feature_values_lookup ON feature_values (feature_definition_id, exchange, symbol, time DESC);"
    )

    # ------------------------------------------------------------------
    # 3. Candles - continuous aggregate dérivé de raw_market_data (Phase 4 §5.1)
    #    Maintenu automatiquement par TimescaleDB, jamais rempli manuellement.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE MATERIALIZED VIEW ohlcv_candles_1m
        WITH (timescaledb.continuous) AS
        SELECT
            exchange,
            symbol,
            time_bucket('1 minute', time) AS bucket,
            first(price, time) AS open,
            max(price)         AS high,
            min(price)         AS low,
            last(price, time)  AS close,
            sum(quantity)      AS volume
        FROM raw_market_data
        GROUP BY exchange, symbol, bucket
        WITH NO DATA;
        """
    )
    # Rafraîchissement : valeur initiale prudente (Phase 6 §8), à ajuster
    # empiriquement dès la collecte réelle (Phase 7).
    op.execute(
        """
        SELECT add_continuous_aggregate_policy('ohlcv_candles_1m',
            start_offset => INTERVAL '3 hours',
            end_offset   => INTERVAL '1 minute',
            schedule_interval => INTERVAL '1 minute');
        """
    )

    # ------------------------------------------------------------------
    # 4. Décisions, risque, exécution (tables relationnelles classiques - Phase 4 §5.3/5.4)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE decisions (
            id                      BIGSERIAL PRIMARY KEY,
            strategy_id             BIGINT NOT NULL REFERENCES strategies(id),
            exchange                TEXT NOT NULL,
            symbol                  TEXT NOT NULL,
            time                    TIMESTAMPTZ NOT NULL DEFAULT now(),
            success_probability     DOUBLE PRECISION NOT NULL,
            expected_value          DOUBLE PRECISION NOT NULL,
            risk_reward_ratio       DOUBLE PRECISION NOT NULL,
            verdict                 TEXT NOT NULL CHECK (verdict IN ('signal', 'no_signal')),
            feature_snapshot_ids    BIGINT[] NOT NULL  -- références feature_values pour traçabilité (Phase 4 §7)
        );
        """
    )
    op.execute("CREATE INDEX ix_decisions_symbol_time ON decisions (symbol, time DESC);")

    op.execute(
        """
        CREATE TABLE risk_checks (
            id              BIGSERIAL PRIMARY KEY,
            decision_id     BIGINT NOT NULL REFERENCES decisions(id),
            rule_name       TEXT NOT NULL,
            passed          BOOLEAN NOT NULL,
            reason          TEXT,
            time            TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX ix_risk_checks_decision ON risk_checks (decision_id);")

    op.execute(
        """
        CREATE TABLE orders (
            id                  BIGSERIAL PRIMARY KEY,
            risk_check_id       BIGINT NOT NULL REFERENCES risk_checks(id),
            exchange            TEXT NOT NULL,
            symbol              TEXT NOT NULL,
            side                TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
            execution_mode      TEXT NOT NULL CHECK (execution_mode IN ('backtest', 'paper', 'real')),
            requested_price     NUMERIC(20, 8),
            requested_quantity  NUMERIC(20, 8) NOT NULL,
            filled_price        NUMERIC(20, 8),
            filled_quantity     NUMERIC(20, 8),
            slippage            NUMERIC(12, 8),
            status              TEXT NOT NULL CHECK (status IN ('pending', 'filled', 'partially_filled', 'cancelled', 'rejected')),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX ix_orders_symbol_status ON orders (symbol, status);")

    op.execute(
        """
        CREATE TABLE positions (
            id                  BIGSERIAL PRIMARY KEY,
            exchange            TEXT NOT NULL,
            symbol              TEXT NOT NULL,
            execution_mode      TEXT NOT NULL CHECK (execution_mode IN ('backtest', 'paper', 'real')),
            opened_at           TIMESTAMPTZ NOT NULL,
            closed_at           TIMESTAMPTZ,
            entry_price         NUMERIC(20, 8) NOT NULL,
            exit_price          NUMERIC(20, 8),
            quantity            NUMERIC(20, 8) NOT NULL,
            realized_pnl        NUMERIC(20, 8),
            unrealized_pnl      NUMERIC(20, 8),
            status              TEXT NOT NULL CHECK (status IN ('open', 'closed'))
        );
        """
    )
    op.execute("CREATE INDEX ix_positions_status ON positions (status, symbol);")

    # ------------------------------------------------------------------
    # 5. Journal transverse (Phase 4 §5.5)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE events_journal (
            id              BIGSERIAL PRIMARY KEY,
            source_module   TEXT NOT NULL,
            event_type      TEXT NOT NULL,
            payload         JSONB NOT NULL,
            time            TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX ix_events_journal_time ON events_journal (time DESC);")
    op.execute("CREATE INDEX ix_events_journal_source ON events_journal (source_module, event_type);")

    # ------------------------------------------------------------------
    # 6. Backtesting (Phase 4 §5.6)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE backtest_runs (
            id              BIGSERIAL PRIMARY KEY,
            strategy_id     BIGINT NOT NULL REFERENCES strategies(id),
            period_start    TIMESTAMPTZ NOT NULL,
            period_end      TIMESTAMPTZ NOT NULL,
            parameters      JSONB NOT NULL,
            executed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE backtest_results (
            id                  BIGSERIAL PRIMARY KEY,
            backtest_run_id     BIGINT NOT NULL REFERENCES backtest_runs(id),
            sharpe_ratio        DOUBLE PRECISION,
            sortino_ratio       DOUBLE PRECISION,
            calmar_ratio        DOUBLE PRECISION,
            max_drawdown        DOUBLE PRECISION,
            profit_factor       DOUBLE PRECISION,
            expectancy          DOUBLE PRECISION,
            ulcer_index         DOUBLE PRECISION,
            total_trades        INTEGER
        );
        """
    )

    # ------------------------------------------------------------------
    # 7. Politiques de compression et de rétention (Phase 4 §6 - table exacte)
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE raw_market_data SET (timescaledb.compress, timescaledb.compress_segmentby = 'exchange, symbol');"
    )
    op.execute("SELECT add_compression_policy('raw_market_data', INTERVAL '7 days');")
    op.execute("SELECT add_retention_policy('raw_market_data', INTERVAL '90 days');")

    op.execute(
        "ALTER TABLE order_book_snapshots SET (timescaledb.compress, timescaledb.compress_segmentby = 'exchange, symbol');"
    )
    op.execute("SELECT add_compression_policy('order_book_snapshots', INTERVAL '3 days');")
    op.execute("SELECT add_retention_policy('order_book_snapshots', INTERVAL '30 days');")

    op.execute(
        "ALTER TABLE feature_values SET (timescaledb.compress, timescaledb.compress_segmentby = 'feature_definition_id, exchange, symbol');"
    )
    op.execute("SELECT add_compression_policy('feature_values', INTERVAL '7 days');")
    # Pas de retention_policy sur feature_values en V1 : alignée manuellement sur
    # la donnée source tant que le besoin réel n'est pas mesuré (Phase 6 §8).

    # ohlcv_candles_1m et funding_rates : conservées indéfiniment (Phase 4 §6),
    # aucune politique de rétention appliquée.


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS ohlcv_candles_1m CASCADE;")
    op.execute("DROP TABLE IF EXISTS backtest_results CASCADE;")
    op.execute("DROP TABLE IF EXISTS backtest_runs CASCADE;")
    op.execute("DROP TABLE IF EXISTS events_journal CASCADE;")
    op.execute("DROP TABLE IF EXISTS positions CASCADE;")
    op.execute("DROP TABLE IF EXISTS orders CASCADE;")
    op.execute("DROP TABLE IF EXISTS risk_checks CASCADE;")
    op.execute("DROP TABLE IF EXISTS decisions CASCADE;")
    op.execute("DROP TABLE IF EXISTS feature_values CASCADE;")
    op.execute("DROP TABLE IF EXISTS funding_rates CASCADE;")
    op.execute("DROP TABLE IF EXISTS order_book_snapshots CASCADE;")
    op.execute("DROP TABLE IF EXISTS raw_market_data CASCADE;")
    op.execute("DROP TABLE IF EXISTS strategies CASCADE;")
    op.execute("DROP TABLE IF EXISTS feature_definitions CASCADE;")
