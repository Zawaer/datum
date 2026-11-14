# Public demo image: FastAPI app + solvers, CPU only. Data, weights and secrets are mounted, never baked in.
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 tesseract-ocr tesseract-ocr-eng curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
# tesseract with one OpenMP thread per process (callers run tiles / variants side by side instead). Its default spins
# one thread per core; with several tesseracts at once on the 4-core VM a 4000 px tile took 43 s instead of 4 s.
# Only tesseract: the Python process keeps its OpenMP threads for torch.
RUN printf '#!/bin/sh\nOMP_THREAD_LIMIT=1 exec /usr/bin/tesseract "$@"\n' > /usr/local/bin/tesseract \
    && chmod 755 /usr/local/bin/tesseract

# Claude Code CLI (the frontier-model fallback calls it one-shot, no tools); wrapped by claude-capped below
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && npm install -g @anthropic-ai/claude-code@2.1.322 && claude --version

RUN pip install torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cpu
COPY deploy/requirements.txt /tmp/req.txt
RUN pip install -r /tmp/req.txt

RUN useradd -m -u 1000 bp
WORKDIR /app
COPY bp/ bp/
COPY app/ app/
COPY deploy/claude-capped /usr/local/bin/claude-capped
COPY deploy/warm.py warm.py
RUN mkdir -p cache runs && chown -R bp /app

USER bp
ENV BP_DATA=/srv/bundle/dataset CLAUDE_CLI=/usr/local/bin/claude-capped CLAUDE_REAL=claude \
    BP_SPEND_LEDGER=/app/cache/spend/ledger.jsonl HF_HUB_OFFLINE=1 YOLO_OFFLINE=1 \
    YOLO_CONFIG_DIR=/app/cache/yolo DISABLE_AUTOUPDATER=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
    CLAUDE_CODE_MAX_OUTPUT_TOKENS=2048
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/drawings?limit=0 >/dev/null || exit 1
# Proxy headers are trusted only from Docker's private address pools (Caddy reaches the app over the compose network,
# whose subnet Docker picks at creation) and loopback, never from '*': the rate limiter keys on the resolved client.
# bp/crosscheck.py reads its second-detector thresholds from cache/crosscheck/ (a volume): copy them in at start
CMD ["sh", "-c", "mkdir -p cache/crosscheck && cp -f /srv/bundle/xcheck/cc_second_thresholds_*.json cache/crosscheck/ 2>/dev/null; exec uvicorn app.server:app --host 0.0.0.0 --port 8000 --workers 1 --no-server-header --proxy-headers --forwarded-allow-ips '127.0.0.1,172.16.0.0/12,192.168.0.0/16,10.0.0.0/8'"]
