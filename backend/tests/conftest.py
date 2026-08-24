"""Fixture partagée par toute la suite de tests.

Migre le schéma une seule fois, en tout début de session, pour tous les
tests qui touchent une vraie base (test_api.py, test_auth.py via
TestClient) - corrige une lacune préexistante : aucun conftest.py
n'existait, seul `tests/test_migrations.py` appliquait les migrations,
de façon `scope="module"` et donc seulement pour ses propres tests.
Selon l'ordre de collecte de pytest (alphabétique par défaut), les
tests de `test_api.py`/`test_auth.py` s'exécutaient avant que quoi que
ce soit n'ait migré la base, d'où des erreurs `relation "..." does not
exist`.
"""

import subprocess

import pytest


@pytest.fixture(scope="session", autouse=True)
def migrated_schema() -> None:
    subprocess.run(["alembic", "upgrade", "head"], check=True)
