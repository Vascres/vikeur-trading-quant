"""Tests de la Phase 6 : migration initiale.

Nécessite une base TimescaleDB accessible via la variable d'environnement
DATABASE_URL (fournie par le service `postgres` en CI - Phase 5, ci.yml).
"""

import subprocess

import psycopg2
import pytest


@pytest.fixture(scope="module", autouse=True)
def apply_migrations():
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    yield
    subprocess.run(["alembic", "downgrade", "base"], check=True)


@pytest.fixture
def db_connection():
    import os

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    yield conn
    conn.close()


def test_hypertables_created(db_connection):
    """Vérifie que les 4 hypertables attendues sont bien enregistrées par TimescaleDB (Phase 4 §6)."""
    expected = {"raw_market_data", "order_book_snapshots", "funding_rates", "feature_values"}
    with db_connection.cursor() as cur:
        cur.execute("SELECT hypertable_name FROM timescaledb_information.hypertables;")
        actual = {row[0] for row in cur.fetchall()}
    assert expected.issubset(actual)


def test_continuous_aggregate_created(db_connection):
    with db_connection.cursor() as cur:
        cur.execute("SELECT view_name FROM timescaledb_information.continuous_aggregates;")
        views = {row[0] for row in cur.fetchall()}
    assert "ohlcv_candles_1m" in views


def test_compression_policy_active(db_connection):
    """Vérifie que raw_market_data a bien une politique de compression après 7 jours (Phase 4 §6)."""
    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT hypertable_name FROM timescaledb_information.jobs
            WHERE proc_name = 'policy_compression'
            AND hypertable_name = 'raw_market_data';
            """
        )
        assert cur.fetchone() is not None


def test_retention_policy_active(db_connection):
    """Vérifie que order_book_snapshots a bien une politique de rétention de 30 jours (Phase 4 §6)."""
    with db_connection.cursor() as cur:
        cur.execute(
            """
            SELECT hypertable_name FROM timescaledb_information.jobs
            WHERE proc_name = 'policy_retention'
            AND hypertable_name = 'order_book_snapshots';
            """
        )
        assert cur.fetchone() is not None


def test_order_requires_valid_risk_check(db_connection):
    """Un ordre ne peut jamais exister sans un risk_check valide (traçabilité - Phase 4 §7)."""
    with db_connection.cursor() as cur:
        with pytest.raises(psycopg2.errors.NotNullViolation):
            cur.execute(
                """
                INSERT INTO orders (exchange, symbol, side, execution_mode,
                                     requested_quantity, status)
                VALUES ('binance', 'BTCUSDT', 'buy', 'paper', 0.01, 'pending');
                """
            )
    db_connection.rollback()


def test_feature_definition_immutability_by_convention(db_connection):
    """Vérifie que la contrainte UNIQUE(name, version) empêche la duplication d'une version existante
    (le versionnement figé - Phase 4 §5.2 - repose sur la discipline applicative + cette contrainte)."""
    with db_connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO feature_definitions (name, version, description, logic_hash)
            VALUES ('spread', 1, 'Spread bid-ask', 'abc123');
            """
        )
        db_connection.commit()
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute(
                """
                INSERT INTO feature_definitions (name, version, description, logic_hash)
                VALUES ('spread', 1, 'Nouvelle logique', 'def456');
                """
            )
    db_connection.rollback()
