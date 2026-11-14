# Public demo deployment

The demo runs on one small CPU VM (Docker: the app + Caddy with automatic HTTPS) and is served **only under a
secret path**: `https://<ip-with-dashes>.sslip.io/<SECRET_PREFIX>/`. Every other path, including `/`, is a bare
404. The prefix lives in `data/secrets/demo_path.txt` (chmod 600) and on the VM in `/opt/bp/site.env`; it is
never committed, posted or written into docs.

## What is where

| file | what |
|---|---|
| `build_bundle.py` | builds `deploy/bundle/` (gitignored): tour drawings + a curated sample per source, their questions, each source's `LICENSE.md`, run summaries for `/results`, the CubiCasa YOLO weights (primary + calibration) and the cross-check second detector with its thresholds (`xcheck/`). The dataset is non-commercial with per-file licences: the bundle only goes to the demo VM, never into git or anywhere public. |
| `Dockerfile`, `requirements.txt` | CPU-only app image (torch CPU wheels, Claude Code CLI). No data or secrets inside. |
| `compose.yml` | `app` (uvicorn, healthcheck, `restart: unless-stopped`) + `caddy` (ports 80/443). |
| `Caddyfile` | `handle_path /{$PREFIX}/*` → app; `/robots.txt` disallows all; everything else 404; no `Server` header, `X-Robots-Tag: noindex, nofollow`, `Referrer-Policy: no-referrer`, no CORS. |
| `claude-capped` | stands in for the `claude` CLI (`CLAUDE_CLI`): logs each call's cost to a ledger and refuses calls once the daily cap is reached. |
| `setup_vm.sh` | one-time VM setup: Docker if missing, ufw allowing only 22/80/443. |
| `deploy.sh` | rsync code + bundle, write the env files, rebuild and restart, wait for health. |
| `warm.py` | fills the IFC / Swiss / mesh caches (paid calls disabled) and prints a small accuracy check. |
| `verify.py` | checks the secrecy rules, runs the tour, the scoreboard and one ask per source in headless Chromium, and measures latency. |

## App settings (env, all off unless set; see the top of `app/server.py`)

- `BP_ROOT_PATH=/<SECRET_PREFIX>`: the app rewrites its own page/script URLs to live under the prefix (Caddy strips it).
- `BP_RATE_LIMIT=30/600`: 30 asks + uploads per client IP per 10 minutes (HTTP 429 after that).
- `BP_DAILY_USD_CAP=5` with `BP_SPEND_LEDGER`: $5/day (UTC) for paid model calls. `claude-capped` enforces it;
  when it is hit, frontier paths abstain and the answer says why. The deterministic solvers (Swiss, CubiCasa,
  IFC) cost $0 and keep answering.
- `BP_DATA`: the bundle's dataset folder. `BP_VLM_URL` (optional): the fine-tuned VLM server; without it, that
  path abstains.

## Steps

```bash
# 1. once: put the VM's IP in hand, key in data/secrets/verda/id_verda
.venv/bin/python deploy/build_bundle.py                  # -> deploy/bundle/ (~300 MB)
deploy/deploy.sh <vm-ip> --setup --warm                  # first deploy

# 2. redeploy after a code change (rebuilds the image, keeps caches and the TLS cert volumes)
deploy/deploy.sh <vm-ip>

# 3. check it
.venv/bin/python deploy/verify.py https://<ip-with-dashes>.sslip.io/<SECRET_PREFIX>
```

Today's paid spend on the VM:
`ssh root@<vm-ip> 'docker exec deploy-app-1 cat /app/cache/spend/ledger.jsonl' | tail`.

Rotate the prefix: write a new one to `data/secrets/demo_path.txt`
(`python3 -c "import secrets; print('d-' + secrets.token_urlsafe(18))"`) and run `deploy/deploy.sh <vm-ip>`.
