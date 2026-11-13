#!/usr/bin/env bash
# One-time VM setup (Ubuntu 24.04, run as root on the VM): Docker + compose, firewall 22/80/443 only.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q ufw rsync
command -v docker >/dev/null || apt-get install -y -q docker.io docker-compose-v2
systemctl enable --now docker
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
mkdir -p /opt/bp/src /opt/bp/bundle
chmod 700 /opt/bp
docker --version && docker compose version
