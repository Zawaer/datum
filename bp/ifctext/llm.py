"""Minimal no-tools Claude call through the Claude Code CLI, with a spend log.

`ask(prompt, system, model)` -> {"text", "cost_usd", "error"?}. Every call appends one line to
cache/llm_spend.jsonl (tag, model, cost) so paid usage can be audited: `python -m bp.ifctext.llm`.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

CLI = os.environ.get("CLAUDE_CLI") or os.environ.get("CLAUDE_CODE_EXECPATH") or "claude"
SPEND_LOG = Path(os.environ.get("BP_CACHE", "cache")) / "llm_spend.jsonl"
_lock = threading.Lock()


def ask(prompt: str, system: str, model: str = "haiku", tag: str = "", timeout: int = 240, retries: int = 2) -> dict:
    cmd = [CLI, "-p", prompt, "--model", model, "--output-format", "json", "--tools", "",
           "--system-prompt", system, "--strict-mcp-config", "--setting-sources", "", "--max-turns", "1"]
    err = None
    for attempt in range(retries + 1):
        with tempfile.TemporaryDirectory(prefix="bpllm_") as d:
            try:
                out = subprocess.run(cmd, cwd=d, capture_output=True, text=True, timeout=timeout)
                res = json.loads(out.stdout)
            except Exception as e:  # noqa: BLE001
                err = repr(e)[:300]
                time.sleep(2 * (attempt + 1))
                continue
        cost = float(res.get("total_cost_usd") or 0.0)
        _log(tag, model, cost)
        if res.get("is_error"):
            err = str(res.get("result"))[:300]
            time.sleep(2 * (attempt + 1))
            continue
        return {"text": res.get("result") or "", "cost_usd": cost}
    return {"text": "", "cost_usd": 0.0, "error": err}


def _log(tag, model, cost):
    SPEND_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _lock, open(SPEND_LOG, "a") as f:
        f.write(json.dumps({"t": round(time.time()), "tag": tag, "model": model, "cost_usd": cost}) + "\n")


def spend() -> dict:
    tot = {}
    if SPEND_LOG.exists():
        for line in SPEND_LOG.read_text().splitlines():
            r = json.loads(line)
            tot[r["tag"]] = tot.get(r["tag"], 0.0) + r["cost_usd"]
    return tot


if __name__ == "__main__":
    s = spend()
    for k, v in sorted(s.items()):
        print(f"{k:20s} ${v:.3f}")
    print(f"{'TOTAL':20s} ${sum(s.values()):.3f}")
