# Live VLM second opinion (Qwen3-VL-8B + LoRA r3 on a GPU box)

The CubiCasa cross-check (`bp/crosscheck.py`) uses the fine-tuned VLM as its second opinion. For dataset
questions it reads **precomputed** answers (`cache/vlm/demo_secondopinion.jsonl`, `runs/vlm_r3_cubicasa_test_full.jsonl`);
those always come first and are never re-asked. With a server configured, everything else gets a **live**
answer from the same model:

- uploads that are a single-page raster residential plan (the condition under which `bp/router.py` sends an upload
  to the CubiCasa detector), count questions;
- CubiCasa dataset drawings asked a question with no precomputed answer (typed wordings).

Model: base `Qwen/Qwen3-VL-8B-Instruct` + LoRA `cache/vlm/runs/q3vl8b_r3/checkpoint-2200` (the checkpoint
behind every shipped second-opinion number; `train/vlm/README.md`), served as LoRA `bpvlm`.

## Pieces

| file | what |
|---|---|
| `deploy/vlm/serve.sh` | one command from our machine: firewall (mandatory), venv, base weights, adapter rsync, model server on 127.0.0.1:8000 as systemd unit `bp-vlm` (on boot, restart on failure), Caddy TLS on 443 (Let's Encrypt, `<ip-dashed>.sslip.io`), API key, health + https checks, writes `data/secrets/vlm.env` |
| `deploy/vlm/hf_server.py` | the default backend: transformers + PEFT (`bp.vlm.infer.LocalRunner`) behind the same OpenAI-compatible API |
| `bp/vlm/live.py` | client: `live_second_opinion(image_path, question)` -> `{"answer", "confidence", "evidence", ...}` or `None`; `python -m bp.vlm.live [image question]` = health + one ask |
| `deploy/vlm/check.py` | asks 3+ test questions live and compares count / boxes / latency with the precomputed answers |
| `deploy/vlm/stub_server.py` | OpenAI-compatible stub that replays the precomputed replies (tests without a GPU) |
| `deploy/deploy.sh` | forwards `BP_VLM_URL` / `BP_VLM_KEY` from `data/secrets/vlm.env` into the app's env file, if that file exists |

The client uses the eval's exact request (`bp.vlm.infer.RemoteRunner`: system prompt and image budget from
`bp/vlm/format.py`, image pre-resized to the training size, greedy, `max_tokens` 2048, logprobs for the
confidence) and reads the reply with the solver's own code (`bp.solvers.vlm.answer_from_reply`), so a live
answer has the precomputed shape: the count plus one normalised box per item. `app/static/app.js` needs no change.

## Env (demo app)

| var | default | |
|---|---|---|
| `BP_VLM_URL` | unset = off | `https://<box-ip-dashed>.sslip.io/v1` |
| `BP_VLM_KEY` | — | bearer key (`BP_VLM_API_KEY` also read) |
| `BP_VLM_SERVED` | `bpvlm` | LoRA name on the server |
| `BP_VLM_LIVE_TIMEOUT` | 20 | hard limit per ask (s); slower -> no second opinion for that ask. serve.sh writes 45 for the hf backend |
| `BP_VLM_LIVE_RETRY` | 60 | after a failure, skip the server this long (a dead box costs one timeout a minute) |
| `BP_VLM_LIVE_STREAMS` | 8 | concurrent live asks; more are skipped, not queued. A slot is freed only when its request has really ended |

Unset, down, slow, wrong key: the cross-check behaves exactly as before (precomputed answer, else the v3
detector, else no second opinion). It never raises. Successful replies are cached in memory per
(file, mtime, question).

## Backend and network (as deployed on 2026-11-14)

- **Backend: transformers, not vLLM.** On the confidential-compute RTX PRO 6000 Blackwell box, `vllm==0.33.0`
  returned garbage tokens for the base model too (FLASH_ATTN and TRITON_ATTN, with and without
  `--enforce-eager`; the top logprobs were already wrong), while transformers on the same GPU answered
  correctly. `--backend hf` serves through `bp.vlm.infer.LocalRunner`, the repo's local inference path. Cost: one
  ask at a time, ~23 tokens/s: 2-10 s for most questions, ~30 s for a 20-door plan, hence the 45 s client limit.
  On an ordinary H100/A100, `--backend vllm` (the server behind the precomputed answers) is ~10x faster.
- **Checked against the precomputed second opinion** (`deploy/vlm/check.py --n 5`, test drawings): same count
  5/5, mean box IoU 0.92-1.00, confidence within 0.01 except one dense door plan (0.54 -> 0.72).
- **Network:** no private network to the demo VM, so the model server listens on 127.0.0.1 only and Caddy
  terminates TLS on 443 with a Let's Encrypt certificate for `<vm-ip>.sslip.io`. ufw: 22 open, 80 open
  (ACME challenge and redirect only), 443 only from the demo VM (<vm-ip>), everything else denied. The key
  is a bearer token over TLS; it lives in `data/secrets/vlm.env` (here) and `/etc/bp-vlm/env` (box), both chmod 600.
- **Boot:** `bp-vlm` and `caddy` are enabled systemd units; `ExecStartPre` sets the confidential-compute GPU
  ready state (otherwise CUDA fails with error 802 after every boot). The certificate is kept on disk and renewed
  by Caddy.

## Go live

```bash
# 1. box: firewall, install, adapter, key, systemd, TLS, health + https checks (~10 min the first time)
deploy/vlm/serve.sh <box-ip> --allow-from <demo-vm-ip> --smoke          # --backend vllm on a non-CC GPU
# 2. compare with the precomputed second opinion through a tunnel (443 is closed to everyone but the demo VM)
ssh -i data/secrets/verda/id_verda -N -L 18731:127.0.0.1:8000 root@<box-ip> &
( set -a; . data/secrets/vlm.env; set +a; BP_VLM_URL=http://127.0.0.1:18731/v1 BP_VLM_LIVE_TIMEOUT=60 \
  .venv/bin/python deploy/vlm/check.py --n 5 )
# 3. from the demo VM (the path the app uses): 401 without a key = TLS + firewall fine
ssh -i data/secrets/verda/id_verda root@<demo-vm-ip> \
  "curl -s -o /dev/null -w '%{http_code}\n' https://<box-ip-dashed>.sslip.io/v1/models"
# 4. deploy the demo as usual; deploy.sh now carries BP_VLM_URL / BP_VLM_KEY / BP_VLM_LIVE_TIMEOUT
deploy/deploy.sh <demo-vm-ip>
```

Off again: delete (or rename) `data/secrets/vlm.env` and redeploy, or just stop the box (the app falls back to
the precomputed answers; uploads then get no second opinion, as before). Box logs:
`ssh root@<box> journalctl -u bp-vlm -f` (one line per ask: question, image size, tokens, seconds).

## Test without a GPU

```bash
.venv/bin/python deploy/vlm/stub_server.py --port 18123 --key testkey &
BP_VLM_URL=http://127.0.0.1:18123/v1 BP_VLM_KEY=testkey .venv/bin/python deploy/vlm/check.py --n 3
```
