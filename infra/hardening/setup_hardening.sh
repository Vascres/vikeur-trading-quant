#!/usr/bin/env bash
#
# Durcissement serveur (Phase 20, §4) - à exécuter UNE FOIS, manuellement,
# en root sur le VPS Fornex (Phase 3), après la première connexion.
#
# Ce script est volontairement interactif à certaines étapes (SSH) pour
# ne jamais risquer de vous couper l'accès au serveur par erreur.

set -euo pipefail

echo "==> Mise à jour du système..."
apt-get update && apt-get upgrade -y

echo "==> Installation de ufw, fail2ban, unattended-upgrades..."
apt-get install -y ufw fail2ban unattended-upgrades

echo "==> Configuration du firewall (ufw) - Phase 3, §4..."
ufw default deny incoming
ufw default allow outgoing
ufw allow 80/tcp
ufw allow 443/tcp

read -r -p "Port SSH à utiliser (recommandé : non standard, ex. 2222) : " SSH_PORT
ufw allow "${SSH_PORT}/tcp"
ufw --force enable

echo "==> Configuration de fail2ban sur le port SSH ${SSH_PORT}..."
cat > /etc/fail2ban/jail.local <<EOF
[sshd]
enabled = true
port = ${SSH_PORT}
maxretry = 5
bantime = 3600
EOF
systemctl restart fail2ban

echo "==> Activation des mises à jour de sécurité automatiques..."
dpkg-reconfigure -plow unattended-upgrades

echo "==> Durcissement SSH (manuel, prudence) :"
echo "    1. Vérifiez que votre clé publique est bien dans /root/.ssh/authorized_keys"
echo "    2. Modifiez /etc/ssh/sshd_config :"
echo "       Port ${SSH_PORT}"
echo "       PasswordAuthentication no"
echo "       PermitRootLogin prohibit-password"
echo "    3. Testez la connexion sur le nouveau port AVANT de redémarrer sshd :"
echo "       ssh -p ${SSH_PORT} root@<ip_vps>"
echo "    4. Une fois confirmé : systemctl restart sshd"
echo ""
echo "==> Durcissement terminé (hors étape SSH manuelle ci-dessus, volontairement non automatisée)."
