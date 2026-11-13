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
        # "sonnet+twins": also hand Claude the drawing's sibling files (same drawing in other formats:
        # DXF/SVG/PNG twins, and the source .ifc of an IFC plan PDF), the same inputs our solvers may use.
        v = variant or "sonnet"
        self.twins = v.endswith("+twins")
        self.model = v.removesuffix("+twins")
        self.root = data_root()

    def siblings(self, src: Path):
        out = [p for p in src.parent.glob(src.stem + ".*") if p != src and p.suffix.lower() != ".md"]
        model = src.parent / (src.stem.split("_plan-")[0] + ".ifc")
        if model.exists() and model != src:
            out.append(model)
        return out

    def __call__(self, q):
        src = self.root / q["path"]
        ext = src.suffix.lower()
        with tempfile.TemporaryDirectory(prefix="bpq_") as d:
            dst = Path(d) / f"drawing{ext}"
            shutil.copy(src, dst)
            extra = []
            if self.twins:
                for sib in self.siblings(src):
                    name = "model.ifc" if sib.suffix.lower() == ".ifc" else f"drawing{sib.suffix.lower()}"
                    if not (Path(d) / name).exists():
                        shutil.copy(sib, Path(d) / name)
                        extra.append(name)
            text_files = ext in (".ifc", ".dxf", ".svg") or any(n.endswith((".ifc", ".dxf", ".svg")) for n in extra)
            tools = "Read,Grep" if text_files else "Read"
            prompt = f"The drawing is ./drawing{ext} . Question: {q['question']}"
            if extra:
                prompt += (" The same drawing is also available in other formats: "
                           + ", ".join(f"./{n}" for n in extra)
                           + " (DXF/SVG/IFC are text files: use Grep/Read on them; the IFC is the BIM model the plan was rendered from).")
            elif ext == ".ifc":
                prompt += " (It is an IFC STEP text file; use Grep/Read on it.)"
            cmd = [CLI, "-p", prompt, "--model", self.model, "--output-format", "json",
                   "--tools", tools, "--allowedTools", tools, "--system-prompt", SYSTEM,
                   "--strict-mcp-config", "--setting-sources", "", "--max-turns", "20" if self.twins else "12"]
            try:
                out = subprocess.run(cmd, cwd=d, capture_output=True, text=True, timeout=600)
                res = json.loads(out.stdout)
            except Exception as e:  # noqa: BLE001
                return {"answer": None, "confidence": 0, "evidence": [], "cost_usd": 0.0,
                        "method": f"claude-{self.model}" + ("+twins" if self.twins else ""), "error": repr(e)[:300]}
        text = res.get("result") or ""
        m = re.findall(r"ANSWER:\s*(.+)", text)
        ans = m[-1].strip() if m else (text.strip().splitlines()[-1] if text.strip() else None)
        return {"answer": ans, "confidence": 0.5, "evidence": [], "cost_usd": res.get("total_cost_usd", 0.0),
                "method": f"claude-{self.model}" + ("+twins" if self.twins else ""), "raw": text[-1500:], "turns": res.get("num_turns")}
