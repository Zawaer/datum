#!/usr/bin/env bash
# On the GPU box (after train/vlm/setup_remote.sh): serve Qwen3-VL-8B + the r3 LoRA with vLLM and answer every
# cubicasa dev-val question (train/vlm/make_dev_rows.py) with 16 request streams.
#   rsync cache/vlm_dev and cache/vlm/runs/q3vl8b_r3/final to /root/bp-vlm/, then (in tmux):
#   bash /root/bp-vlm/train/vlm/devval_remote.sh   -> cache/vlm_dev/devval_r3.jsonl ("DEVVAL DONE" in the log)
set -uo pipefail
cd ${BP_DIR:-/root/bp-vlm}
export HF_HOME=$PWD/cache/hf
A=${ADAPTER:-cache/vlm/runs/q3vl8b_r3/final}
if ! curl -sf localhost:8000/v1/models >/dev/null; then
  tmux kill-session -t serve 2>/dev/null
  tmux new -d -s serve "PATH=$PWD/.venv-vllm/bin:\$PATH .venv-vllm/bin/vllm serve Qwen/Qwen3-VL-8B-Instruct \
    --enable-lora --lora-modules r3final=$A --max-lora-rank 32 --max-model-len 8192 \
    --limit-mm-per-prompt.image 1 --host 127.0.0.1 --port 8000 > cache/vlm_dev/serve.log 2>&1"
  for i in $(seq 1 120); do curl -sf localhost:8000/v1/models >/dev/null && break; sleep 5; done
fi
curl -sf localhost:8000/v1/models | head -c 300; echo
t0=$(date +%s)
for s in $(seq 0 15); do
  BP_VLM_URL=http://127.0.0.1:8000/v1 BP_VLM_SERVED=r3final .venv/bin/python train/vlm/eval_vlm.py \
    --data cache/vlm_dev --file devval_cc.jsonl --in-order --n 100000 --shard $s/16 \
    --out cache/vlm_dev/devval_r3_s$s.jsonl > cache/vlm_dev/devval_r3_s$s.log 2>&1 &
done
wait
cat cache/vlm_dev/devval_r3_s*.jsonl > cache/vlm_dev/devval_r3.jsonl
echo "DEVVAL DONE $(wc -l < cache/vlm_dev/devval_r3.jsonl) rows in $(( $(date +%s) - t0 )) s"
