#!/usr/bin/env bash
#
# Test de persistance du kill switch (Phase 20, §5 ; signalé en Phase 13, §9).
# À exécuter sur le VPS, depuis infra/.
#
# Vérifie que l'activation du kill switch (Phase 13, §4) survit à un
# redémarrage du conteneur Redis, grâce à la persistance AOF déjà
# configurée dans docker-compose.yml (Phase 5).

set -euo pipefail

echo "==> Activation du kill switch..."
docker compose exec redis redis-cli -a "${REDIS_PASSWORD}" SET risk:kill_switch 1

echo "==> Redémarrage forcé du conteneur Redis..."
docker compose restart redis

echo "==> Attente de la disponibilité de Redis..."
sleep 5

echo "==> Vérification de l'état après redémarrage..."
VALUE=$(docker compose exec redis redis-cli -a "${REDIS_PASSWORD}" GET risk:kill_switch | tr -d '\r')

if [[ "${VALUE}" == "1" ]]; then
    echo "✅ Test réussi : le kill switch a survécu au redémarrage (persistance AOF confirmée)."
else
    echo "❌ ÉCHEC : le kill switch a été perdu après redémarrage. Vérifier la configuration AOF de Redis."
    exit 1
fi

echo "==> Nettoyage : désactivation du kill switch après le test..."
docker compose exec redis redis-cli -a "${REDIS_PASSWORD}" SET risk:kill_switch 0
