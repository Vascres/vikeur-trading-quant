"""Stockage des sauvegardes (Module 2, §4.2).

Compatible avec tout fournisseur S3 (Backblaze B2, AWS S3...) via
BACKUP_STORAGE_ENDPOINT - aucune dépendance à un fournisseur précis.
"""

import os
import re
from datetime import UTC, datetime, timedelta

import boto3

BACKUP_BUCKET = os.environ.get("BACKUP_BUCKET", "projet-quant-backups")

_FILENAME_PATTERN = re.compile(r"backup_(\d{8})_(\d{6})\.sql\.gz")


def _build_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["BACKUP_STORAGE_ENDPOINT"],
        aws_access_key_id=os.environ["BACKUP_STORAGE_ACCESS_KEY"],
        aws_secret_access_key=os.environ["BACKUP_STORAGE_SECRET_KEY"],
    )


def upload_backup(local_path: str, filename: str) -> None:
    client = _build_client()
    client.upload_file(local_path, BACKUP_BUCKET, filename)


def list_backup_keys() -> list[str]:
    client = _build_client()
    response = client.list_objects_v2(Bucket=BACKUP_BUCKET)
    return [obj["Key"] for obj in response.get("Contents", [])]


def parse_backup_timestamp(filename: str) -> datetime | None:
    """Extrait la date d'un nom de fichier de sauvegarde (Module 2, §4).
    Retourne None si le nom ne correspond pas au format attendu -
    ignoré plutôt que deviné (même principe que le mapping de symboles, Phase 8).
    """
    match = _FILENAME_PATTERN.match(filename)
    if not match:
        return None
    date_part, time_part = match.groups()
    return datetime.strptime(f"{date_part}{time_part}", "%Y%m%d%H%M%S").replace(tzinfo=UTC)


def filter_expired_backups(filenames: list[str], now: datetime, retention_days: int) -> list[str]:
    """Fonction pure : retourne les noms de fichiers à supprimer (Module 2, §9)."""
    cutoff = now - timedelta(days=retention_days)
    expired = []
    for filename in filenames:
        timestamp = parse_backup_timestamp(filename)
        if timestamp is not None and timestamp < cutoff:
            expired.append(filename)
    return expired


def delete_backups(filenames: list[str]) -> None:
    if not filenames:
        return
    client = _build_client()
    client.delete_objects(
        Bucket=BACKUP_BUCKET,
        Delete={"Objects": [{"Key": name} for name in filenames]},
    )
