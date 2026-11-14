#!/usr/bin/env bash
# On the GPU box (Ubuntu + NVIDIA driver; idempotent).
#   scp yolo_cc.tar code.tar data.yaml + this script to /root/bp-det/, then: bash /root/bp-det/train/cubicasa/remote/setup.sh
set -euo pipefail
D=/root/bp-det; cd $D
[ -d train ] || tar -xf code.tar
[ -d cache/yolo_cc/images ] || { mkdir -p cache && tar -xf yolo_cc.tar -C cache; }
cp data.yaml cache/yolo_cc/data.yaml
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
[ -x .venv/bin/python ] || uv venv -p 3.12 .venv   # own venv; torch comes from uv's cache if bp-vlm installed it
uv pip install -p .venv/bin/python --index-strategy unsafe-best-match \
  --extra-index-url https://download.pytorch.org/whl/cu128 "torch==2.11.0" torchvision "ultralytics==8.4.212" pillow numpy
command -v tmux >/dev/null || { apt-get update -q && apt-get install -yq tmux; }
.venv/bin/python -c "import torch, ultralytics; print(torch.__version__, torch.cuda.get_device_name(0), ultralytics.__version__)"
echo "train: $(ls cache/yolo_cc/images/train | wc -l)  val: $(ls cache/yolo_cc/images/val | wc -l)"
nproc; free -g | head -2; df -h /root | tail -1
