#!/usr/bin/env bash
# Idempotent setup of a fresh Ubuntu CUDA VM for train/vlm (tested: Ubuntu 24.04, H100, CUDA 12.9 driver).
#
# On your machine (repo root), copy code + the training subset (dev-split drawings only; never test images):
#   H=root@<vm-ip>
#   rsync -az --relative bp/__init__.py bp/data.py bp/vlm train/vlm $H:/root/bp-vlm/
#   rsync -az cache/vlm/train.jsonl cache/vlm/val.jsonl cache/vlm/stats.json cache/vlm/img $H:/root/bp-vlm/cache/vlm/
# Then on the VM:
#   bash /root/bp-vlm/train/vlm/setup_remote.sh [model id ...]
set -euo pipefail
DIR=${BP_DIR:-/root/bp-vlm}
MODELS=${*:-Qwen/Qwen3-VL-8B-Instruct}
cd "$DIR"

export DEBIAN_FRONTEND=noninteractive
command -v tmux >/dev/null && command -v rsync >/dev/null || { apt-get update -q && apt-get install -yq tmux rsync; }
dpkg -s python3-dev build-essential >/dev/null 2>&1 || { apt-get update -q && apt-get install -yq python3-dev python3-venv build-essential; }  # triton builds kernels
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

[ -d .venv ] || uv venv -p 3.12 .venv
# pinned set the pipeline was tested with (torch cu128 wheels run on CUDA >= 12.8 drivers)
uv pip install -p .venv/bin/python --index-strategy unsafe-best-match \
  --extra-index-url https://download.pytorch.org/whl/cu128 \
  "torch==2.11.0" "torchvision" "transformers==5.23.0" "peft==0.21.3" "trl==1.18.0" "accelerate==1.15.0" \
  "datasets" "pillow" "numpy" "jinja2>=3.1.6" "qwen-vl-utils" "huggingface_hub[hf_xet]" "bitsandbytes" "tensorboard" "kernels"  # kernels: prebuilt flash-attn (--attn kernels-community/flash-attn2)
# vLLM for serving the adapter lives in its own venv (it pins its own torch)
if [ "${WITH_VLLM:-1}" = 1 ] && [ ! -x .venv-vllm/bin/vllm ]; then
  uv venv -p 3.12 .venv-vllm && uv pip install -p .venv-vllm/bin/python "vllm==0.33.0" || echo "vllm install failed (serving optional)"
fi

export HF_HOME=${HF_HOME:-$DIR/cache/hf}
for m in $MODELS; do .venv/bin/hf download "$m" >/dev/null && echo "downloaded $m"; done

.venv/bin/python - <<'EOF'
import torch, transformers, peft, trl
print("torch", torch.__version__, "cuda", torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else "")
print("transformers", transformers.__version__, "peft", peft.__version__, "trl", trl.__version__)
EOF
test -f cache/vlm/train.jsonl && echo "data: $(wc -l < cache/vlm/train.jsonl) train / $(wc -l < cache/vlm/val.jsonl) val" \
  || echo "data missing: rsync cache/vlm (see header)"
