"""Frontier baseline: give Claude the drawing file and the question, nothing else.

Runs through the Claude Code CLI in an empty sandbox dir with only the Read tool
(plus Grep for IFC, which is text and far too large for a context window).
total_cost_usd is computed by the CLI at API list prices.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from bp.data import data_root

SYSTEM = (
    "You answer quantity-takeoff questions about construction drawings and BIM models. "
    "Look at the provided file carefully. Count exactly; for areas, lengths and volumes give a number "
    "in the unit asked. End your reply with a final line of the form 'ANSWER: <value>' "
    "(a bare number for numeric questions, no units)."
)

CLI = os.environ.get("CLAUDE_CLI") or os.environ.get("CLAUDE_CODE_EXECPATH") or "claude"


class ClaudeSolver:
    def __init__(self, variant=None):
        self.model = variant or "sonnet"
        self.root = data_root()

    def __call__(self, q):
        src = self.root / q["path"]
        ext = src.suffix.lower()
        with tempfile.TemporaryDirectory(prefix="bpq_") as d:
            dst = Path(d) / f"drawing{ext}"
            shutil.copy(src, dst)
            tools = "Read,Grep" if ext == ".ifc" else "Read"
            prompt = f"The drawing is ./drawing{ext} . Question: {q['question']}"
            if ext == ".ifc":
                prompt += " (It is an IFC STEP text file; use Grep/Read on it.)"
            cmd = [CLI, "-p", prompt, "--model", self.model, "--output-format", "json",
                   "--tools", tools, "--allowedTools", tools, "--system-prompt", SYSTEM,
                   "--strict-mcp-config", "--setting-sources", "", "--max-turns", "12"]
            try:
                out = subprocess.run(cmd, cwd=d, capture_output=True, text=True, timeout=600)
                res = json.loads(out.stdout)
            except Exception as e:  # noqa: BLE001
                return {"answer": None, "confidence": 0, "evidence": [], "cost_usd": 0.0,
                        "method": f"claude-{self.model}", "error": repr(e)[:300]}
        text = res.get("result") or ""
        m = re.findall(r"ANSWER:\s*(.+)", text)
        ans = m[-1].strip() if m else (text.strip().splitlines()[-1] if text.strip() else None)
        return {"answer": ans, "confidence": 0.5, "evidence": [], "cost_usd": res.get("total_cost_usd", 0.0),
                "method": f"claude-{self.model}", "raw": text[-1500:], "turns": res.get("num_turns")}
