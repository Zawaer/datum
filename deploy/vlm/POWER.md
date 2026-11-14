# On-demand GPU: the start/stop hook contract

The live second opinion (`deploy/vlm/README.md`) runs on the GPU box `stoa-live-gpu`. Instead of keeping it on,
the demo app starts it when a raster plan is uploaded and stops it after 12 idle minutes, under a daily cost cap.
The demo VM holds **no cloud-provider API key**: it calls one HTTPS hook that the infra side runs, and the hook
holds the key. This file is the contract for that hook. Our side is `bp/vlm/gpu_power.py`; a reference stub is
`deploy/vlm/power_stub.py`.

## Request

```
POST <hook URL>                         (HTTPS; any path, e.g. https://<infra-host>/gpu/stoa-live-gpu)
Authorization: Bearer <shared secret>
Content-Type: application/json

{"action": "start"}      or      {"action": "stop"}      or      {"action": "status"}
```

- One box per hook URL: the box is fixed on the infra side (`stoa-live-gpu`), never taken from the request.
- Client timeout: 10 s. Do not wait for the boot inside the request: accept, kick off the start, return.
- `status` is optional (we do not depend on it); we tell readiness from the model server itself
  (`GET https://<vm-ip>.sslip.io/v1/models` with the VLM key → the served model `bpvlm` listed).

## Response

`200` (or `202` for a start that has begun), JSON body:

```json
{"state": "starting", "eta_s": 140}
```

| field | values | |
|---|---|---|
| `state` | `"stopped"` · `"starting"` · `"running"` · `"stopping"` | the box after the action |
| `eta_s` | integer seconds, optional | for `start`: expected time until the model server answers; we show it to the user ("~2 min"). Omit if unknown (we assume 150) |

Semantics:

- **Idempotent.** `start` on a running or starting box returns its current state, does not reboot it and does
  not create a second box. `stop` on a stopped box returns `"stopped"`. We may repeat either.
- **Stop = no billing.** `stop` must bring hourly cost to zero (power off / delete the instance as Verda bills it),
  while keeping the disk with the weights, the adapter, `/etc/bp-vlm/env` and the Caddy certificate, so the next
  start serves the same model at the same address.
- **Same address after a start.** The model must come back at `<vm-ip>` / `https://<vm-ip>.sslip.io/v1`
  with the same key; `bp-vlm` and `caddy` are enabled systemd units, so a normal boot does it. If the IP can
  change, tell us before wiring (the TLS name and our `BP_VLM_URL` depend on it).

Errors (we treat any non-2xx as "the hook failed", log it, show no second opinion, and retry no sooner than 60 s):

| status | when |
|---|---|
| `401` | missing or wrong secret (do not say which) |
| `400` | unknown `action` / bad JSON |
| `402` or `409` | the infra side's own cap is reached: refuse `start` (`{"state": "stopped", "error": "cap"}`) |
| `429` | rate limit exceeded (`Retry-After` header welcome) |
| `5xx` | provider error |

## Auth

- A shared secret of at least 32 random bytes (e.g. `openssl rand -hex 32`), sent only as
  `Authorization: Bearer …` over HTTPS. Compare in constant time. Never log it.
- Optionally restrict the hook to the demo VM's IP (<vm-ip>).
- We keep it in `data/secrets/gpu_power.env` (chmod 600, never committed); `deploy/deploy.sh` forwards it.
- Rotation: give us the new secret, we redeploy; accepting the old and new one for a few minutes is enough.

## Rate limits

What we send:

- at most **1 `start` per 60 s** (one start covers every upload while the box boots or runs) and
  **1 `stop` per 60 s**; in practice a few starts and stops per day;
- a `stop` after **12 minutes** without a live model call (`BP_GPU_IDLE_MIN`), and when our daily cap is reached.

What the hook should accept: **10 requests per minute** per secret; above that `429`.

## Cost cap

Two guards; the infra one is the authoritative one.

1. **Ours (local).** We record every accepted start and stop in `cache/gpu_power.jsonl` and estimate today's
   (UTC) cost as on-time × $2.89/h (`BP_GPU_USD_PER_H`). At **$15/day** (`BP_GPU_DAILY_USD_CAP`, about 5 h 10 min)
   we refuse to start and stop a running box. This survives app restarts but cannot see time we did not cause.
2. **Infra (please implement).** A hard cap per UTC day on the box's billed time (same $15, or what Rene sets):
   refuse `start` with `402`/`409` when reached, and stop the box when it is reached.
3. **Dead-man stop (please implement).** Our app could die while the box is on (a redeploy, a crash), and then
   nobody sends `stop`. Stop the box after **6 hours** of continuous running whatever we send (longer than our
   own cap allows in a day, so it never cuts off a normal session).

## What we need back to wire it

Hook URL, the secret (via the secret-drop form, not the board), the measured boot-to-ready time, and whether the
IP is stable. Then wiring is one file on our side:

```
# data/secrets/gpu_power.env  (chmod 600)
BP_GPU_HOOK_URL=https://<infra-host>/gpu/stoa-live-gpu
BP_GPU_HOOK_SECRET=<secret>
BP_GPU_BOOT_S=<measured seconds>          # optional; the hook's eta_s overrides it per start
# optional: BP_GPU_IDLE_MIN=12  BP_GPU_DAILY_USD_CAP=15  BP_GPU_USD_PER_H=2.89  BP_GPU_BOOT_MAX_S=900
```

Without `BP_GPU_HOOK_URL` nothing changes: the box is treated as always on and readiness comes from its health.

## How the app behaves (for reference)

- A single-page raster plan is uploaded → `start` (non-blocking; the box boots while the user types).
- The answer comes at once from the detector / general reader. If the live second opinion is missing because
  the box is starting, the answer card shows "Warming up our vision model for a second opinion… (~2 min)" with a
  thin progress bar; the page polls `GET /api/upload_second/{key}`, and when the box is healthy the second
  opinion is computed for that question and replaces the line. Dataset drawings never wait (precomputed).
- `GET /api/gpu` → `{"state": "off" | "starting" | "ready", "eta_s", "spent_today", "cap_usd", "hooked", ...}`.
- A start that is not healthy after 15 minutes (`BP_GPU_BOOT_MAX_S`) counts as failed: the line goes away, and the
  idle watcher still sends `stop` so a half-booted box is not left billed.

## Test without a GPU

```bash
.venv/bin/python deploy/vlm/power_stub.py --port 18761 --boot 20 --key testkey &   # hook + a VLM up 20 s after start
BP_VLM_URL=http://127.0.0.1:18761/v1 BP_VLM_KEY=testkey \
BP_GPU_HOOK_URL=http://127.0.0.1:18761/hook BP_GPU_HOOK_SECRET=stub-secret BP_GPU_LEDGER=/tmp/gpu_power.jsonl \
  .venv/bin/python -m uvicorn app.server:app --host 0.0.0.0 --port 3152
.venv/bin/python -m pytest -q tests/test_gpu_power.py
```
