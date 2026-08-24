"""Tests du Module 2 : sauvegardes réelles (fonctions pures uniquement,
sans réseau ni base de données réelle - Module 2, §9)."""

from datetime import UTC, datetime

from backup.dump import build_backup_filename, build_pg_dump_command
from backup.scheduling import seconds_until_next_run
from backup.storage import filter_expired_backups, parse_backup_timestamp


def test_seconds_until_next_run_later_today():
    now = datetime(2026, 1, 1, 1, 0, 0, tzinfo=UTC)
    result = seconds_until_next_run(now, target_hour_utc=3)
    assert result == 2 * 3600  # 2h avant 03h00


def test_seconds_until_next_run_tomorrow_if_already_passed():
    now = datetime(2026, 1, 1, 5, 0, 0, tzinfo=UTC)
    result = seconds_until_next_run(now, target_hour_utc=3)
    assert result == 22 * 3600  # 22h avant demain 03h00


def test_build_pg_dump_command_extracts_connection_parts():
    command = build_pg_dump_command(
        "postgresql://quant_app:secret@timescaledb:5432/quant_platform", "/tmp/out.sql"
    )
    assert "pg_dump" in command
    assert "timescaledb" in command
    assert "quant_app" in command
    assert "quant_platform" in command
    assert "secret" not in command  # le mot de passe ne doit jamais apparaître dans la commande


def test_build_backup_filename_format():
    now = datetime(2026, 3, 15, 3, 0, 0, tzinfo=UTC)
    filename = build_backup_filename(now)
    assert filename == "backup_20260315_030000.sql.gz"


def test_parse_backup_timestamp_valid():
    result = parse_backup_timestamp("backup_20260315_030000.sql.gz")
    assert result == datetime(2026, 3, 15, 3, 0, 0, tzinfo=UTC)


def test_parse_backup_timestamp_ignores_unrelated_filenames():
    assert parse_backup_timestamp("autre_fichier.txt") is None


def test_filter_expired_backups_keeps_recent():
    now = datetime(2026, 3, 15, tzinfo=UTC)
    filenames = ["backup_20260314_030000.sql.gz"]  # 1 jour
    expired = filter_expired_backups(filenames, now, retention_days=30)
    assert expired == []


def test_filter_expired_backups_flags_old():
    now = datetime(2026, 3, 15, tzinfo=UTC)
    filenames = ["backup_20260101_030000.sql.gz"]  # > 30 jours
    expired = filter_expired_backups(filenames, now, retention_days=30)
    assert expired == ["backup_20260101_030000.sql.gz"]


def test_filter_expired_backups_ignores_malformed_names():
    now = datetime(2026, 3, 15, tzinfo=UTC)
    expired = filter_expired_backups(["fichier_invalide.txt"], now, retention_days=30)
    assert expired == []
