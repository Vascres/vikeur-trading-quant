"""Dump PostgreSQL (Module 2, §4.1)."""

import gzip
import shutil
import subprocess
from datetime import UTC, datetime
from urllib.parse import urlparse


def build_pg_dump_command(database_url: str, output_path: str) -> list[str]:
    """Construit la commande pg_dump à partir d'une DATABASE_URL - fonction
    pure, ne s'exécute pas elle-même (testable sans base réelle).
    """
    parsed = urlparse(database_url)
    return [
        "pg_dump",
        "--host",
        parsed.hostname or "localhost",
        "--port",
        str(parsed.port or 5432),
        "--username",
        parsed.username or "",
        "--no-password",  # le mot de passe passe par PGPASSWORD (variable d'environnement)
        "--format",
        "plain",
        "--file",
        output_path,
        parsed.path.lstrip("/"),
    ]


def build_backup_filename(now: datetime | None = None) -> str:
    """Nom de fichier horodaté, trié naturellement (Module 2, §4)."""
    now = now or datetime.now(tz=UTC)
    return f"backup_{now.strftime('%Y%m%d_%H%M%S')}.sql.gz"


def run_pg_dump(database_url: str, password: str, working_dir: str, now: datetime | None = None) -> str:
    """Exécute pg_dump réellement, compresse le résultat, retourne le
    chemin du fichier compressé.
    """
    filename = build_backup_filename(now)
    raw_path = f"{working_dir}/{filename.removesuffix('.gz')}"
    compressed_path = f"{working_dir}/{filename}"

    command = build_pg_dump_command(database_url, raw_path)

    import os

    env = os.environ.copy()
    env["PGPASSWORD"] = password

    subprocess.run(command, check=True, env=env)

    with open(raw_path, "rb") as raw_file, gzip.open(compressed_path, "wb") as compressed_file:
        shutil.copyfileobj(raw_file, compressed_file)

    os.remove(raw_path)
    return compressed_path
