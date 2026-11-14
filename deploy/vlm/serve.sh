#!/usr/bin/env bash
# Serve the fine-tuned VLM (Qwen3-VL-8B-Instruct + LoRA r3 checkpoint-2200) for the demo's live second opinion.
#
#   deploy/vlm/serve.sh <gpu-box-ip> --allow-from <demo-vm-ip> [--allow-from ...] [--backend hf|vllm]
#                       [--hostname <name>] [--smoke] [--adapter <dir>]
#
# Run from the repo root on our machine. One command on a fresh Ubuntu + CUDA box (>= 40 GB GPU):
#   1. firewall (mandatory): ufw allows 22 from anywhere, 80 from anywhere (ACME certificate challenge and a
#      redirect only), 443 only from the --allow-from addresses; nothing else (the model port is never exposed)
#   2. apt basics, uv, a venv; base model download; adapter rsync (no training state)
#   3. the model server on 127.0.0.1:8000 (OpenAI-compatible, LoRA served as "bpvlm"), systemd unit bp-vlm
#      (starts on boot, restarts on failure):
#        --backend hf    (default) transformers + PEFT, deploy/vlm/hf_server.py: the repo's own local inference
#                        path (bp.vlm.infer.LocalRunner); one ask at a time
#        --backend vllm  vllm==0.33.0 (pin of train/vlm/setup_remote.sh, which produced the precomputed answers);
#                        faster and batched, but it returned garbage on the confidential-compute RTX PRO 6000
#                        (2026-11-14, even for the base model), so check it with --smoke before relying on it
#   4. TLS: Caddy on 443 with an automatic Let's Encrypt certificate for <hostname> (default <ip-with-dashes>.sslip.io),
#      reverse-proxying to 127.0.0.1:8000, so the bearer key never crosses the internet in clear text
#   5. an API key generated once into data/secrets/vlm.env (gitignored, chmod 600), copied to the box as
#      /etc/bp-vlm/env (chmod 600, read by the unit; never on a command line, never printed)
#   6. waits until /v1/models lists bpvlm, then writes BP_VLM_URL=https://<hostname>/v1 into data/secrets/vlm.env,
#      which deploy/deploy.sh forwards to the demo app
# --smoke  afterwards, one real ask through an SSH tunnel (python -m bp.vlm.live) on a demo drawing whose
#          precomputed answer is known (4 doors), to check prompt / format / adapter end to end
# Idempotent: rerun to update the adapter or restart the server. Same SSH key / known_hosts as deploy/deploy.sh.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
IP=${1:?usage: deploy/vlm/serve.sh <gpu-box-ip> --allow-from <demo-vm-ip> [--backend hf|vllm] [--hostname <name>] [--smoke]}; shift
HOST=""; ALLOW=(); SMOKE=0; BACKEND=hf
ADAPTER=${BP_VLM_ADAPTER_DIR:-cache/vlm/runs/q3vl8b_r3/checkpoint-2200}  # the shipped second opinion's checkpoint
while [ $# -gt 0 ]; do case $1 in
  --hostname) HOST=$2; shift;; --allow-from) ALLOW+=("$2"); shift;; --smoke) SMOKE=1;; --adapter) ADAPTER=$2; shift;;
  --backend) BACKEND=$2; shift;; *) echo "unknown option $1" >&2; exit 2;; esac; shift; done
[ ${#ALLOW[@]} -gt 0 ] || { echo "--allow-from <demo-vm-ip> is required (443 is opened to those addresses only)" >&2; exit 2; }
case $BACKEND in hf|vllm) ;; *) echo "--backend hf|vllm" >&2; exit 2;; esac
HOST=${HOST:-${IP//./-}.sslip.io}
VLLM_PIN=${VLLM_PIN:-0.33.0}
BASE=Qwen/Qwen3-VL-8B-Instruct
KEY=${BP_SSH_KEY:-data/secrets/verda/id_verda}
SSHO=(-i "$KEY" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=data/secrets/verda/known_hosts)
R="root@$IP"
ssh_() { ssh "${SSHO[@]}" "$R" "$@"; }
ENVF=data/secrets/vlm.env
test -f "$ADAPTER/adapter_model.safetensors" -a -f "$ADAPTER/adapter_config.json" || { echo "no adapter in $ADAPTER" >&2; exit 1; }

echo "== API key"
umask 077
if ! grep -qs '^BP_VLM_KEY=' "$ENVF"; then
  mkdir -p data/secrets
  echo "BP_VLM_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" >> "$ENVF"
  echo "generated a new key into $ENVF"
fi
chmod 600 "$ENVF"
umask 022

echo "== firewall: 22 + 80 open, 443 only from ${ALLOW[*]}, the model port closed"
ssh_ "command -v ufw >/dev/null || { apt-get update -q && apt-get install -yq ufw; }
  ufw allow 22/tcp >/dev/null; ufw allow 80/tcp >/dev/null
  for n in ${ALLOW[*]}; do ufw allow from \$n to any port 443 proto tcp >/dev/null
    ufw delete allow from \$n to any port 8000 proto tcp >/dev/null 2>&1 || true; done
  ufw delete allow 8000/tcp >/dev/null 2>&1 || true
  ufw default deny incoming >/dev/null; ufw --force enable >/dev/null; ufw status | sed -n '5,20p'"

echo "== box setup ($BACKEND backend + base weights; first run ~10 min)"
ssh_ "VLLM_PIN=$VLLM_PIN BASE=$BASE BACKEND=$BACKEND bash -s" <<'REMOTE'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
command -v rsync >/dev/null && command -v curl >/dev/null && command -v caddy >/dev/null \
  || { apt-get update -q && apt-get install -yq rsync curl caddy; }
dpkg -s python3-dev build-essential >/dev/null 2>&1 || { apt-get update -q && apt-get install -yq python3-dev python3-venv build-essential; }
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
mkdir -p /opt/bp-vlm/adapter /opt/bp-vlm/hf /opt/bp-vlm/src /etc/bp-vlm && chmod 700 /etc/bp-vlm
cd /opt/bp-vlm
[ -d .venv ] || uv venv -p 3.12 .venv
if [ "$BACKEND" = vllm ]; then
  .venv/bin/python -c "import vllm, sys; sys.exit(vllm.__version__ != '$VLLM_PIN')" 2>/dev/null \
    || uv pip install -p .venv/bin/python "vllm==$VLLM_PIN"
else  # transformers + PEFT (versions of train/vlm/setup_remote.sh; keeps a torch that is already there)
  .venv/bin/python -c "import torch, transformers, peft, accelerate" 2>/dev/null \
    || uv pip install -p .venv/bin/python torch "transformers>=5.20,<5.24" "peft==0.21.3" "accelerate==1.15.0" \
         pillow "huggingface_hub[hf_xet]"
fi
HF_HOME=/opt/bp-vlm/hf .venv/bin/python -c "from huggingface_hub import snapshot_download as d; d('$BASE')" >/dev/null
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
.venv/bin/python -c "import torch, transformers; print('torch', torch.__version__, 'transformers', transformers.__version__)"
REMOTE

echo "== adapter + server code -> box"
rsync -azR --delete --exclude __pycache__ -e "ssh ${SSHO[*]}" bp/__init__.py bp/vlm deploy/vlm/hf_server.py "$R:/opt/bp-vlm/src/"
rsync -az --delete --exclude trainer_state.json --exclude training_args.bin --exclude 'optimizer*' \
  --exclude 'scheduler*' --exclude 'rng_state*' -e "ssh ${SSHO[*]}" "$ADAPTER/" "$R:/opt/bp-vlm/adapter/"

echo "== key -> box (chmod 600, read by systemd)"
{ printf 'VLLM_API_KEY=%s\n' "$(sed -n 's/^BP_VLM_KEY=//p' "$ENVF" | tail -1)"
  echo "HF_HOME=/opt/bp-vlm/hf"
  echo "HF_HUB_OFFLINE=1"; } | ssh_ 'umask 077; cat > /etc/bp-vlm/env'

echo "== systemd unit ($BACKEND)"
if [ "$BACKEND" = vllm ]; then
  # Same flags as the server that produced the precomputed answers (train/vlm/README.md "serve base + adapter").
  # FlashInfer JIT-builds kernels at start: ninja (venv) and nvcc (CUDA toolkit) must be on PATH.
  EXEC="/opt/bp-vlm/.venv/bin/vllm serve Qwen/Qwen3-VL-8B-Instruct --enable-lora --lora-modules bpvlm=/opt/bp-vlm/adapter \\
  --max-lora-rank 32 --max-model-len 8192 --limit-mm-per-prompt.image 1 --gpu-memory-utilization 0.90 \\
  --host 127.0.0.1 --port 8000"
else
  EXEC="/opt/bp-vlm/.venv/bin/python /opt/bp-vlm/src/deploy/vlm/hf_server.py --adapter /opt/bp-vlm/adapter --host 127.0.0.1 --port 8000"
fi
# The client (bp.vlm.infer.RemoteRunner) resizes every image to the training budget itself (bp.vlm.format:
# 1024²..1280² px for plans, at most 1792²), so the server never resizes again.
ssh_ 'cat > /etc/systemd/system/bp-vlm.service' <<UNIT
[Unit]
Description=Blueprints VLM (Qwen3-VL-8B + LoRA bpvlm, $BACKEND), OpenAI-compatible on 127.0.0.1:8000 (Caddy TLS on 443)
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/opt/bp-vlm
EnvironmentFile=/etc/bp-vlm/env
# confidential-compute GPUs (Verda "CC" images) boot "not-ready": CUDA then fails with error 802 until the
# ready state is set; a failure (ordinary GPUs) is ignored
ExecStartPre=-/usr/bin/nvidia-smi conf-compute -srs 1
Environment=PATH=/opt/bp-vlm/.venv/bin:/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=CUDA_HOME=/usr/local/cuda
ExecStart=$EXEC
Restart=on-failure
RestartSec=10
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
UNIT
ssh_ 'systemctl daemon-reload && systemctl enable bp-vlm >/dev/null 2>&1 && systemctl restart bp-vlm'

echo "== Caddy: https://$HOST -> 127.0.0.1:8000"
printf '%s {\n\treverse_proxy 127.0.0.1:8000\n}\n' "$HOST" | ssh_ 'cat > /etc/caddy/Caddyfile && systemctl enable caddy >/dev/null 2>&1 && systemctl restart caddy'

echo "== waiting for the server (model load, up to 15 min)"
ssh_ 'set -a; . /etc/bp-vlm/env; set +a
  for i in $(seq 180); do
    if curl -sf -m 5 -H "Authorization: Bearer $VLLM_API_KEY" http://127.0.0.1:8000/v1/models | grep -q "\"bpvlm\""; then
      echo "healthy after $((i * 5)) s: bpvlm served"; exit 0; fi
    systemctl is-active -q bp-vlm || { echo "bp-vlm stopped:"; journalctl -u bp-vlm -n 40 --no-pager; exit 1; }
    sleep 5
  done; echo "not healthy after 15 min:"; journalctl -u bp-vlm -n 40 --no-pager; exit 1'

echo "== TLS check from the box (certificate for $HOST)"
ssh_ "set -a; . /etc/bp-vlm/env; set +a
  for i in \$(seq 24); do
    if curl -sf -m 10 -H \"Authorization: Bearer \$VLLM_API_KEY\" https://$HOST/v1/models | grep -q bpvlm; then
      echo 'https ok'; exit 0; fi; sleep 5; done
  echo 'https not ready:'; journalctl -u caddy -n 15 --no-pager; exit 1"
umask 077
grep -vE '^BP_VLM_(URL|LIVE_TIMEOUT)=' "$ENVF" > "$ENVF.tmp" || true
echo "BP_VLM_URL=https://$HOST/v1" >> "$ENVF.tmp"
# transformers decodes ~23 tokens/s (one box ~ 20 tokens): a 20-door plan takes ~30 s, so the hf backend gets 45 s
# (uploads have 75 s in app/server.py; the detector answers in a few); vLLM stays at the client's default 20 s
[ "$BACKEND" = hf ] && echo "BP_VLM_LIVE_TIMEOUT=45" >> "$ENVF.tmp"
mv "$ENVF.tmp" "$ENVF" && chmod 600 "$ENVF"
umask 022
echo "wrote $ENVF: BP_VLM_URL=https://$HOST/v1 (+ key). Next: deploy/deploy.sh <demo-vm-ip> picks it up."

if [ "$SMOKE" = 1 ]; then
  echo "== smoke test through an SSH tunnel (precomputed answer for this ask: 4 doors)"
  PORT=18731
  ssh "${SSHO[@]}" -N -L "$PORT:127.0.0.1:8000" "$R" & TUN=$!
  trap 'kill $TUN 2>/dev/null' EXIT
  sleep 3
  PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
  ( set -a; . "$ENVF"; set +a; BP_VLM_URL=http://127.0.0.1:$PORT/v1 BP_VLM_LIVE_TIMEOUT=60 \
    $PY -m bp.vlm.live "${BP_DATA:-data/full/junction-dataset}/data/cubicasa5k/colorful-10052.png" \
    "How many doors are shown on this floor plan? Count doorways fitted with a door; open doorways without a door leaf do not count." )
fi
