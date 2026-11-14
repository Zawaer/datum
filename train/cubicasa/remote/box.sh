#!/usr/bin/env bash
# Local helper for the GPU boxes (Verda key + pinned known_hosts; never prints the key).
#   bash train/cubicasa/remote/box.sh <ip> push-det          # dataset + code + setup.sh -> /root/bp-det, run setup
#   bash train/cubicasa/remote/box.sh <ip> train <name> <train.py args...>   # tmux "det_<name>" on the box
#   bash train/cubicasa/remote/box.sh <ip> push-vlm          # dev-val rows/images + r3 adapter + code -> /root/bp-vlm
#   bash train/cubicasa/remote/box.sh <ip> devval            # tmux "devval": vLLM + 16 streams (train/vlm/devval_remote.sh)
#   bash train/cubicasa/remote/box.sh <ip> pull              # weights/results back into cache/ (idempotent)
#   bash train/cubicasa/remote/box.sh <ip> sh '<command>'
set -euo pipefail
cd "$(dirname "$0")/../../.."
IP=$1; CMD=$2; shift 2
S=data/secrets/verda
O=(-i $S/id_verda -o BatchMode=yes -o UserKnownHostsFile=$S/known_hosts -o StrictHostKeyChecking=yes -o ConnectTimeout=15)
H=root@$IP
SSH() { ssh "${O[@]}" $H "$@"; }
RS() { rsync -az --partial -e "ssh ${O[*]}" "$@"; }
case $CMD in
  push-det)
    bash train/cubicasa/remote/pack.sh >/dev/null
    SSH mkdir -p /root/bp-det/train/cubicasa/remote
    RS cache/cubicasa/remote/yolo_cc.tar cache/cubicasa/remote/code.tar cache/cubicasa/remote/data.yaml $H:/root/bp-det/
    RS train/cubicasa/remote/setup.sh $H:/root/bp-det/train/cubicasa/remote/
    SSH 'cd /root/bp-det && rm -rf train bp && tar -xf code.tar && bash train/cubicasa/remote/setup.sh' ;;
  train)
    name=$1; shift
    SSH "cd /root/bp-det && mkdir -p cache/cubicasa && tmux new -d -s det_$name 'PYTHONUNBUFFERED=1 .venv/bin/python train/cubicasa/train.py --name $name $* > cache/cubicasa/train_$name.log 2>&1; echo TRAIN EXIT \$? >> cache/cubicasa/train_$name.log'"
    echo "started det_$name on $IP at $(date -u +%FT%TZ)" ;;
  push-vlm)
    SSH mkdir -p /root/bp-vlm/cache/vlm_dev /root/bp-vlm/cache/vlm/runs/q3vl8b_r3
    RS --relative bp/__init__.py bp/data.py bp/vlm bp/cubicasa train/vlm $H:/root/bp-vlm/
    RS cache/vlm_dev/devval_cc.jsonl cache/vlm_dev/img $H:/root/bp-vlm/cache/vlm_dev/
    RS cache/vlm/runs/q3vl8b_r3/final $H:/root/bp-vlm/cache/vlm/runs/q3vl8b_r3/ ;;
  devval)
    SSH "cd /root/bp-vlm && tmux new -d -s devval 'bash train/vlm/devval_remote.sh > cache/vlm_dev/devval.log 2>&1'"
    echo "started devval on $IP at $(date -u +%FT%TZ)" ;;
  pull)
    mkdir -p cache/cubicasa/runs cache/vlm_dev
    RS --exclude '*.jpg' --exclude '*.png' "$H:/root/bp-det/cache/cubicasa/runs/" cache/cubicasa/runs/ 2>/dev/null || true
    RS "$H:/root/bp-det/cache/cubicasa/train_*.log" cache/cubicasa/ 2>/dev/null || true
    RS "$H:/root/bp-vlm/cache/vlm_dev/devval*" cache/vlm_dev/ 2>/dev/null || true ;;
  sh) SSH "$@" ;;
  *) echo "unknown command $CMD"; exit 2 ;;
esac
