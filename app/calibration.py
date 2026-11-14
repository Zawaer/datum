"""What does a confidence mean, and what did frontier models answer? Two small tables the demo reads.

    .venv/bin/python -m app.calibration [runs/router_full_test_v7.jsonl]
        -> app/calibration.json   per-method calibration from the full held-out test run
        -> app/frontier.json      per-question answers of the frontier baselines (400-question test sample)

Both are committed because runs/ is not (and the public bundle strips the baseline runs to cost/latency).

For each method family, accuracy overall and per confidence bin (bins with fewer than MIN_N questions fall
back to the family's overall figure when the app looks them up). The app turns this into a sentence:
"answers like this were right 97.4 % of the time on 3,032 held-out test questions".
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

OUT = Path(__file__).parent / "calibration.json"
FRONTIER_OUT = Path(__file__).parent / "frontier.json"
BASELINES = [  # run name, model label, setting (same order in the app)
    ("sonnet", "Claude Sonnet 5.5", "drawing only"),
    ("sonnetfair", "Claude Sonnet 5.5", "drawing + its CAD/IFC files"),
    ("gemini", "Gemini 3.1 Pro", "drawing only"),
    ("haiku", "Claude Haiku 5.5", "drawing only"),
    ("nemotron", "Nemotron 3.5 Super VL", "drawing only (open model)"),
]
BINS = [0.99, 0.95, 0.9, 0.8, 0.6, 0.4, 0.0]  # lower edges, highest first
MIN_N = 200

FAMILIES = {  # family -> (label, how the answer is made)
    "cubicasa": "plan-symbol detector (CubiCasa raster plans)",
    "swiss": "CAD-layer geometry (Swiss DXF twins)",
    "ifc-geo": "IFC model query (counts and quantities)",
    "ifc-rule": "rule-based IFC report",
    "ifc-llm": "LLM on an IFC fact sheet",
}


def family(method: str) -> str | None:
    m = str(method or "")
    if m.startswith("cubicasa"):
        return "cubicasa"
    if m.startswith("swiss"):
        return "swiss"
    if m.startswith("ifc-text"):
        return "ifc-rule"
    if m.startswith("ifctext"):
        return "ifc-llm"
    if m.startswith("ifc"):
        return "ifc-geo"
    return None


def bin_of(c: float) -> float:
    return next(b for b in BINS if (c or 0) >= b)


def build(run: Path) -> dict:
    fam = collections.defaultdict(lambda: [0, 0, 0])  # n, right, abstained
    bins = collections.defaultdict(lambda: [0, 0])
    for line in open(run):
        r = json.loads(line)
        f = family(r.get("method"))
        if f is None:
            continue
        fam[f][0] += 1
        if r.get("pred") is None:
            fam[f][2] += 1
            continue
        ok = bool(r.get("correct"))
        fam[f][1] += ok
        b = bins[(f, bin_of(r.get("confidence") or 0))]
        b[0] += 1
        b[1] += ok
    out = {"run": run.name, "split": "test", "min_n": MIN_N, "bins": BINS, "families": {}}
    for f, (n, right, abst) in fam.items():
        out["families"][f] = {
            "label": FAMILIES[f], "n": n, "right": right, "abstained": abst,
            "bins": {str(lo): {"n": bins[(f, lo)][0], "right": bins[(f, lo)][1]} for lo in BINS if bins[(f, lo)][0]},
        }
    return out


def build_frontier(runs: Path = Path("runs")) -> dict:
    """{question id: [{model, setting, pred, correct, cost_usd, latency_s}, ...]} from the baseline runs.
    Free-text answers count as right/wrong only where an LLM judge scored them (the .judged files)."""
    out: dict[str, list] = collections.defaultdict(list)
    for name, model, setting in BASELINES:
        judged, plain = runs / f"baseline_{name}_full400.judged.jsonl", runs / f"baseline_{name}_full400.jsonl"
        f = judged if judged.exists() else plain
        if not f.exists():
            continue
        for line in open(f):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if "id" not in r or "pred" not in r:  # stripped copy (public bundle): nothing per question
                continue
            pred = r.get("pred")
            correct = r.get("correct")
            if r.get("type") == "text" and f is plain:
                correct = None
            out[str(r["id"])].append({
                "model": model, "setting": setting, "run": name,
                "pred": pred if not isinstance(pred, str) else pred.strip()[:240],
                "correct": correct, "cost_usd": round(float(r.get("cost_usd") or 0), 6),
                "latency_s": round(float(r.get("latency_s") or 0), 2)})
    return dict(out)


if __name__ == "__main__":
    run = Path(sys.argv[1] if len(sys.argv) > 1 else "runs/router_full_test_v7.jsonl")
    OUT.write_text(json.dumps(build(run), indent=1) + "\n")
    print(OUT.read_text()[:400], "...")
    fr = build_frontier()
    FRONTIER_OUT.write_text(json.dumps(fr, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"{FRONTIER_OUT}: {len(fr)} questions, {sum(map(len, fr.values()))} answers, "
          f"{FRONTIER_OUT.stat().st_size // 1024} KB")
