"""Shared loading, statistics and chart style for the results analysis.

Everything reads runs/*.jsonl written by eval.py; nothing here re-runs a solver.

Systems
-------
* ours      : the router on the full held-out test split (default runs/router_full_test.jsonl).
* frontier  : every runs/baseline_*.jsonl whose questions are all in the current test split
              (a stratified sample, e.g. n=400). New baselines dropped in runs/ are picked up
              automatically; give them a label in LABELS below.
* prior     : guess-the-most-common-answer per question template (runs/prior_full_test.jsonl).

Text answers: whenever a runs/*.judged.jsonl holds an LLM-judge verdict for the same question id and the
same predicted answer, that verdict replaces the token-F1 proxy, for every system alike.
"""
from __future__ import annotations

import collections
import glob
import json
import math
import os
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
IMG = ROOT / "docs" / "img"
OUT = ROOT / "analysis" / "out"

OURS = os.environ.get("BP_OURS_RUN", "router_full_test")
PRIOR = os.environ.get("BP_PRIOR_RUN", "prior_full_test")

# Local compute is not free: price our wall-clock time at a rented-GPU rate so it can sit on a log axis.
# $0.50/h is a typical on-demand price for one consumer-class (RTX 4070/4090-class) cloud GPU.
GPU_USD_PER_HOUR = 0.50

N_BOOT = 10_000
SEED = 20261113

LABELS = {
    "router_full_test": "Ours (router)",
    "prior_full_test": "Template prior",
    "baseline_sonnet_full400": "Claude Sonnet, direct",
    "baseline_haiku_full400": "Claude Haiku, direct",
    "generic_cubicasa_300_haiku": "Generic VLM pipeline (Haiku)",
}

SOURCE_LABEL = {
    "cubicasa5k": "CubiCasa",
    "swiss_dwellings": "Swiss Dwellings",
    "ifc_models": "IFC models",
    "ifc_bench": "IFC bench",
}

# ---------------------------------------------------------------- palette (dataviz reference instance)
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
DIV_NEG = "#e34948"   # under-count arm (red)
DIV_POS = "#2a78d6"   # over-count arm (blue)
DIV_MID = "#d6d5ce"   # neutral midpoint (exact)

# fixed slot per entity (colour follows the system, never its rank)
_SLOT = {"router_full_test": 0, "baseline_sonnet_full400": 1, "baseline_haiku_full400": 2,
         "generic_cubicasa_300_haiku": 3}


def color_of(name: str) -> str:
    if name == PRIOR:
        return MUTED
    if name in _SLOT:
        return SERIES[_SLOT[name]]
    # new systems take the next free slots in discovery order (stable across figures within one run)
    extra = [n for n in discover_frontier() if n not in _SLOT]
    i = 4 + (extra.index(name) if name in extra else 0)
    return SERIES[min(i, len(SERIES) - 1)]


def label_of(name: str) -> str:
    if name in LABELS:
        return LABELS[name]
    n = name.replace("baseline_", "").replace("_full400", "").replace("_", " ")
    return n[:1].upper() + n[1:]


# ---------------------------------------------------------------- loading
def _read(path: Path):
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


@lru_cache(maxsize=None)
def judge_index():
    """(id, str(pred)) -> judge verdict, from every runs/*.judged.jsonl."""
    idx = {}
    for p in sorted(RUNS.glob("*.judged.jsonl")):
        for r in _read(p):
            if "judge_correct" in r and r.get("pred") is not None:
                idx[(r["id"], str(r["pred"]))] = bool(r["judge_correct"])
    return idx


@lru_cache(maxsize=None)
def load(name: str):
    """Rows of runs/<name>.jsonl with text answers re-scored by the LLM judge where a verdict exists."""
    rows = _read(RUNS / f"{name}.jsonl")
    idx = judge_index()
    for r in rows:
        r["proxy_correct"] = r.get("proxy_correct", r["correct"])
        r["text_scoring"] = None
        if r["type"] in ("text", "other"):
            v = idx.get((r["id"], str(r["pred"])))
            if v is not None:
                r["correct"] = v
                r["text_scoring"] = "judge"
            else:
                r["text_scoring"] = "proxy" if r["pred"] is not None else "abstain"
        r["ok"] = bool(r["correct"])
    return rows


@lru_cache(maxsize=None)
def population():
    """(source, type) -> number of questions in the full held-out test split (= ours, which covers all)."""
    return collections.Counter((r["source"], r["type"]) for r in load(OURS))


@lru_cache(maxsize=None)
def discover_frontier():
    """Baseline runs on a sample of the current test split (all ids inside it)."""
    test_ids = {r["id"] for r in load(OURS)}
    out = []
    for p in sorted(glob.glob(str(RUNS / "baseline_*.jsonl"))):
        name = Path(p).name[: -len(".jsonl")]
        if name.endswith(".judged"):
            continue
        ids = {r["id"] for r in _read(Path(p))}
        if ids and ids <= test_ids:
            out.append(name)
    # sonnet first, then haiku, then anything new
    order = {"baseline_sonnet_full400": 0, "baseline_haiku_full400": 1}
    return tuple(sorted(out, key=lambda n: (order.get(n, 9), n)))


def exists(name: str) -> bool:
    return (RUNS / f"{name}.jsonl").exists()


# ---------------------------------------------------------------- statistics
def wilson(k: int, n: int, z: float = 1.959964):
    if n == 0:
        return (float("nan"),) * 3
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, c - h), min(1.0, c + h)


def is_full(rows) -> bool:
    return len(rows) == sum(population().values())


def stratified(rows, value=lambda r: r["ok"], weights=None, n_boot=N_BOOT, seed=SEED):
    """Test-mix re-weighted mean of `value` over a stratified sample, with a stratified-bootstrap 95 % CI.

    Strata are (source, type). Weight of a stratum = its share of the full test split (or `weights`).
    Strata absent from the sample are dropped and the remaining weights renormalised.
    Returns (estimate, lo, hi, n).
    """
    weights = weights or population()
    groups = collections.defaultdict(list)
    for r in rows:
        groups[(r["source"], r["type"])].append(float(value(r)))
    keys = [k for k in groups if weights.get(k, 0) > 0]
    w = np.array([weights[k] for k in keys], float)
    w /= w.sum()
    est = float(sum(wi * np.mean(groups[k]) for wi, k in zip(w, keys)))
    rng = np.random.default_rng(seed)
    boot = np.zeros(n_boot)
    for wi, k in zip(w, keys):
        a = np.array(groups[k])
        idx = rng.integers(0, len(a), size=(n_boot, len(a)))
        boot += wi * a[idx].mean(axis=1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return est, float(lo), float(hi), len(rows)


def accuracy(rows):
    """(estimate, lo, hi, n, method). Full split -> plain mean + Wilson; sample -> re-weighted + bootstrap."""
    if is_full(rows):
        k = sum(r["ok"] for r in rows)
        p, lo, hi = wilson(k, len(rows))
        return p, lo, hi, len(rows), "Wilson"
    e, lo, hi, n = stratified(rows)
    return e, lo, hi, n, "re-weighted, stratified bootstrap"


def acc_wilson(rows):
    k = sum(r["ok"] for r in rows)
    p, lo, hi = wilson(k, len(rows))
    return p, lo, hi, len(rows)


def api_cost_per_1k(rows):
    if is_full(rows):
        return 1000 * sum(r["cost_usd"] for r in rows) / len(rows)
    return 1000 * stratified(rows, value=lambda r: r["cost_usd"], n_boot=1)[0]


def compute_cost_per_1k(rows):
    """Wall-clock seconds per question priced at GPU_USD_PER_HOUR (an upper bound for local solvers)."""
    if is_full(rows):
        s = sum(r["latency_s"] for r in rows) / len(rows)
    else:
        s = stratified(rows, value=lambda r: r["latency_s"], n_boot=1)[0]
    return 1000 * s * GPU_USD_PER_HOUR / 3600


def cubicasa_template(q: str):
    import sys

    sys.path.insert(0, str(ROOT))
    from bp.cubicasa.questions import target

    return target(q)


TEMPLATE_LABEL = {
    "window": "Windows", "door": "Doors", "toilet": "Toilets", "sink": "Sinks",
    "shower_bath": "Showers + baths", "sauna": "Saunas", "kitchen": "Kitchens", "bedroom": "Bedrooms",
    "wc_room": "WC rooms", "bathroom": "Bathrooms", "balcony": "Balconies", "floor": "Floors",
}
TEMPLATE_ORDER = list(TEMPLATE_LABEL)


def solver_family(method: str) -> str:
    m = method or "none"
    if m.startswith("cubicasa"):
        return "CubiCasa detector"
    if m.startswith("swiss"):
        return "Swiss DXF geometry"
    if m.startswith("ifc-text"):
        return "IFC text (rules)"
    if m.startswith("ifc"):
        return "IFC geometry / quantities"
    if m.startswith("claude-sonnet"):
        return "Claude Sonnet, direct"
    if m.startswith("claude-haiku"):
        return "Claude Haiku, direct"
    if m.startswith("generic"):
        return "Generic VLM pipeline (Haiku)"
    return m


# ---------------------------------------------------------------- chart style
def style():
    import matplotlib as mpl

    mpl.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "font.family": "DejaVu Sans", "font.size": 17,
        "axes.titlesize": 22, "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.titlepad": 14,
        "axes.labelsize": 17, "axes.labelcolor": INK2, "axes.edgecolor": AXIS, "axes.linewidth": 1,
        "xtick.color": INK2, "ytick.color": INK2, "xtick.labelsize": 15, "ytick.labelsize": 15,
        "xtick.major.size": 0, "ytick.major.size": 0, "xtick.minor.size": 0, "ytick.minor.size": 0,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 1, "grid.linestyle": "-",
        "axes.spines.top": False, "axes.spines.right": False,
        "legend.frameon": False, "legend.fontsize": 15, "text.color": INK,
        "svg.fonttype": "none", "text.parse_math": False,
    })


def title(ax, head: str, sub: str | None = None):
    """Headline (the takeaway) + a muted method line, both left-aligned above the plot."""
    fig = ax.figure
    ax.set_title("")
    fig.text(0.02, 0.975, head, ha="left", va="top", fontsize=22, fontweight="bold", color=INK)
    if sub:
        fig.text(0.02, 0.975 - 0.055 * (6.2 / fig.get_figheight()), sub, ha="left", va="top",
                 fontsize=15, color=INK2)


def save(fig, stem: str):
    IMG.mkdir(parents=True, exist_ok=True)
    fig.savefig(IMG / f"{stem}.png", dpi=160)
    fig.savefig(IMG / f"{stem}.svg")
    print("wrote", IMG / f"{stem}.png")


def pct(x, d=1):
    return f"{100 * x:.{d}f} %"


def fmt_n(n):
    return f"{n:,}"
