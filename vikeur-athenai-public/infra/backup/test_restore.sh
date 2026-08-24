#!/usr/bin/env bash
#
# Test de restauration (Phase 20, §5 ; signalé en Phase 3, §6).
# Restaure le dernier dump sur une base TEMPORAIRE - ne touche jamais
# la base de production. À exécuter périodiquement (ex. mensuel).

set -euo pipefail

LATEST_DUMP="${1:?Usage: ./test_restore.sh <chemin_vers_le_dernier_dump.sql.gz>}"
TEST_DB_NAME="quant_platform_restore_test"

echo "==> Création d'une base temporaire '${TEST_DB_NAME}'..."
docker compose exec -T timescaledb psql -U "${POSTGRES_USER}" -c "DROP DATABASE IF EXISTS ${TEST_DB_NAME};"
docker compose exec -T timescaledb psql -U "${POSTGRES_USER}" -c "CREATE DATABASE ${TEST_DB_NAME};"

echo "==> Restauration du dump dans la base temporaire..."
gunzip -c "${LATEST_DUMP}" | docker compose exec -T timescaledb psql -U "${POSTGRES_USER}" -d "${TEST_DB_NAME}"

echo "==> Vérification des tables clés..."
for TABLE in decisions positions feature_values events_journal; do
    COUNT=$(docker compose exec -T timescaledb psql -U "${POSTGRES_USER}" -d "${TEST_DB_NAME}" -tAc "SELECT COUNT(*) FROM ${TABLE};")
    echo "    ${TABLE} : ${COUNT} lignes"
done

echo "==> Nettoyage de la base temporaire..."
docker compose exec -T timescaledb psql -U "${POSTGRES_USER}" -c "DROP DATABASE ${TEST_DB_NAME};"

echo "✅ Test de restauration terminé. Vérifiez ci-dessus que les compteurs sont cohérents avec l'activité récente."
