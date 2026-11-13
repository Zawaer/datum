#!/usr/bin/env bash
# Deploy / redeploy the public demo:  deploy/deploy.sh <vm-ip> [--setup] [--warm]
#   --setup  first time only: install Docker + firewall on the VM (deploy/setup_vm.sh)
#   --warm   fill the IFC/Swiss/mesh caches afterwards (paid calls disabled while warming)
# Reads (never prints) data/secrets/anthropic.env and data/secrets/demo_path.txt; both stay out of git.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
IP=${1:?usage: deploy/deploy.sh <vm-ip> [--setup] [--warm]}; shift
SETUP=0; WARM=0
for a in "$@"; do case $a in --setup) SETUP=1;; --warm) WARM=1;; esac; done
KEY=${BP_SSH_KEY:-data/secrets/verda/id_verda}
PREFIX=$(tr -d '\n' < "${BP_PREFIX_FILE:-data/secrets/demo_path.txt}")
SITE=${BP_SITE:-${IP//./-}.sslip.io}
SSHO=(-i "$KEY" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=data/secrets/verda/known_hosts)
R="root@$IP"
ssh_() { ssh "${SSHO[@]}" "$R" "$@"; }

[ "$SETUP" = 1 ] && ssh_ 'bash -s' < deploy/setup_vm.sh
[ -f deploy/bundle/dataset/questions.jsonl ] || .venv/bin/python deploy/build_bundle.py

echo "== sync code + bundle"
rsync -azR --delete --exclude __pycache__ -e "ssh ${SSHO[*]}" \
  bp app deploy/Dockerfile deploy/compose.yml deploy/Caddyfile deploy/claude-capped deploy/requirements.txt \
  deploy/warm.py "$R:/opt/bp/src/"
rsync -az --delete -e "ssh ${SSHO[*]}" deploy/bundle/ "$R:/opt/bp/bundle/"

echo "== secrets + caps (chmod 600 on the VM)"
{ grep -E '^ANTHROPIC_API_KEY=' data/secrets/anthropic.env
  echo "BP_RATE_LIMIT=${BP_RATE_LIMIT:-30/600}"
  echo "BP_DAILY_USD_CAP=${BP_DAILY_USD_CAP:-5}"
  [ -n "${BP_VLM_URL:-}" ] && echo "BP_VLM_URL=$BP_VLM_URL"
  true; } | ssh_ 'umask 077; cat > /opt/bp/app.env'
printf 'SITE=%s\nPREFIX=%s\n' "$SITE" "$PREFIX" | ssh_ 'umask 077; cat > /opt/bp/site.env'

echo "== build + restart"
ssh_ 'cd /opt/bp/src/deploy && docker compose --env-file /opt/bp/site.env up -d --build --remove-orphans 2>&1 | tail -5'
ssh_ 'for i in $(seq 60); do s=$(docker inspect -f "{{.State.Health.Status}}" deploy-app-1 2>/dev/null); [ "$s" = healthy ] && break; sleep 5; done; echo "app: $s"'
if [ "$WARM" = 1 ]; then
  echo "== warm caches"
  ssh_ 'cd /opt/bp/src/deploy && docker compose --env-file /opt/bp/site.env exec -T -e CLAUDE_CLI=/bin/false app python warm.py 2>&1 | tail -8'
fi
echo "done: https://$SITE/<SECRET_PREFIX>/  (prefix in data/secrets/demo_path.txt)"
