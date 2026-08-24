#!/usr/bin/env bash
#
# Déploiement manuel vers le VPS Fornex.
# Exécuté volontairement depuis votre machine — jamais automatique (cf. Phase 5, §3.2).
#
# Usage : ./deploy.sh <tag_image>
# Exemple : ./deploy.sh a1b2c3d

set -euo pipefail

TAG="${1:?Usage: ./deploy.sh <tag_image>}"
VPS_HOST="${VPS_HOST:?Définir la variable d'environnement VPS_HOST (ex: user@ip_vps)}"
REMOTE_DIR="${REMOTE_DIR:-/opt/projet-quant}"

echo "==> Déploiement du tag ${TAG} vers ${VPS_HOST}:${REMOTE_DIR}"
echo "==> Affichage du tag actuellement déployé avant de continuer..."

ssh "${VPS_HOST}" "cd ${REMOTE_DIR} && grep IMAGE_TAG .env || echo 'Aucun tag actuel trouvé'"

read -r -p "Confirmer le déploiement du tag ${TAG} ? [y/N] " confirmation
if [[ "${confirmation}" != "y" && "${confirmation}" != "Y" ]]; then
    echo "Déploiement annulé."
    exit 0
fi

echo "==> Mise à jour du tag d'image sur le VPS..."
ssh "${VPS_HOST}" "cd ${REMOTE_DIR} && sed -i 's/^IMAGE_TAG=.*/IMAGE_TAG=${TAG}/' .env"

echo "==> Pull des nouvelles images..."
ssh "${VPS_HOST}" "cd ${REMOTE_DIR} && docker compose pull"

echo "==> Application des migrations de base de données (Phase 6)..."
ssh "${VPS_HOST}" "cd ${REMOTE_DIR} && docker compose run --rm backend alembic upgrade head"

echo "==> Redémarrage des services..."
ssh "${VPS_HOST}" "cd ${REMOTE_DIR} && docker compose up -d"

echo "==> Vérification de l'état des conteneurs..."
ssh "${VPS_HOST}" "cd ${REMOTE_DIR} && docker compose ps"

echo "==> Déploiement terminé. Pensez à vérifier /health et les logs avant de vous déconnecter."
