"""Vérification purement statique des identifiants de révision Alembic
(17/08/2026) - délibérément séparée de test_migrations.py : aucun besoin
d'une vraie base migrée pour lire des fichiers et une regex, ne doit
jamais hériter de sa fixture `apply_migrations` (autouse, exige
DATABASE_URL et une vraie instance TimescaleDB).
"""

import re
from pathlib import Path


def test_every_migration_revision_id_fits_in_alembic_version_column():
    """Garde-fou ajouté le 17/08/2026, après TROIS violations réelles la
    même nuit (0020/0022/0024 lors de leur création, puis 0027) - la
    colonne `alembic_version.version_num` est un `VARCHAR(32)` (posé par
    Alembic lui-même, jamais redéfini par ce projet) : un identifiant de
    révision plus long fait échouer TOUTE la chaîne de migrations dès
    qu'on l'atteint - `alembic upgrade head`, donc toute la suite de
    tests qui en dépend (`conftest.py::migrated_schema`), jamais une
    erreur localisée à la seule migration fautive."""

    versions_dir = Path(__file__).parent.parent / "migrations" / "versions"
    offenders = []

    for path in sorted(versions_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue
        content = path.read_text()
        match = re.search(r'^revision\s*=\s*"([^"]+)"', content, re.MULTILINE)
        assert match is not None, f"{path.name} n'a pas de ligne 'revision = \"...\"' détectable."
        revision_id = match.group(1)
        if len(revision_id) > 32:
            offenders.append((path.name, revision_id, len(revision_id)))

    assert not offenders, "Identifiant(s) de révision Alembic dépassant VARCHAR(32) : " + ", ".join(
        f"{name} ({rev!r}, {length} car.)" for name, rev, length in offenders
    )
