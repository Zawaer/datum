#!/usr/bin/env python3
"""One-command eval harness.

    python eval.py --solver prior --split test
    python eval.py --solver claude@sonnet --split test --sample 200 --jobs 6

Scores with the official tolerance rules (bp/score.py), prints accuracy by type,
source and language, and logs cost + latency per question to runs/<run>.jsonl.
Every number we publish comes from a runs/*.summary.md written by this script.
"""
import argparse
import collections
import concurrent.futures as cf
import hashlib
import json
import sys
import time
from pathlib import Path

from bp.data import load_questions
from bp.score import is_correct
from bp.solvers import get_solver

try:
    from langdetect import DetectorFactory, detect

    DetectorFactory.seed = 0
except ImportError:  # pragma: no cover
    detect = None


def lang_of(text: str) -> str:
    if detect is None:
        return "?"
    try:
        return detect(text)
    except Exception:  # noqa: BLE001
        return "?"


def stable_hash(s: str) -> int:
    return int(hashlib.sha1(s.encode()).hexdigest()[:12], 16)


def stratified_sample(qs, n):
    """Deterministic sample spread over (source, type) groups."""
    groups = collections.defaultdict(list)
    for q in qs:
        groups[(q["source"], q["type"])].append(q)
    for g in groups.values():
        g.sort(key=lambda q: stable_hash(f"{q['path']}|{q['question']}"))
    out, i = [], 0
    while len(out) < n and any(i < len(g) for g in groups.values()):
        for g in sorted(groups):
            if i < len(groups[g]) and len(out) < n:
                out.append(groups[g][i])
        i += 1
    return out


def table(rows, key):
    by = collections.defaultdict(list)
    for r in rows:
        by[key(r)].append(r)
    lines = ["| group | n | answered | accuracy | precision | $/1k q | s/q |", "|---|---|---|---|---|---|---|"]
    for k in sorted(by, key=lambda k: -len(by[k])) + ["ALL"]:
        g = rows if k == "ALL" else by[k]
        n = len(g)
        ans = [r for r in g if r["correct"] is not None]
        ok = sum(1 for r in g if r["correct"])
        cost = sum(r["cost_usd"] for r in g) / n * 1000
        lat = sum(r["latency_s"] for r in g) / n
        prec = f"{ok / len(ans):.1%}" if ans else "-"
        name = f"**{k}**" if k == "ALL" else k
        lines.append(f"| {name} | {n} | {len(ans) / n:.0%} | {ok / n:.1%} | {prec} | {cost:.2f} | {lat:.2f} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--solver", required=True)
    ap.add_argument("--split", default="test", choices=["dev", "test", "all"])
    ap.add_argument("--source", action="append", help="filter: source name (repeatable)")
    ap.add_argument("--type", action="append", help="filter: question type (repeatable)")
    ap.add_argument("--ext", action="append", help="filter: file extension (repeatable)")
    ap.add_argument("--sample", type=int, help="stratified deterministic sample of N questions")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--name", help="run name (default: solver-split-timestamp)")
    args = ap.parse_args()

    qs = load_questions()
    if args.split != "all":
        qs = [q for q in qs if q["split"] == args.split]
    if args.source:
        qs = [q for q in qs if q["source"] in args.source]
    if args.type:
        qs = [q for q in qs if q["type"] in args.type]
    if args.ext:
        qs = [q for q in qs if q["ext"] in args.ext]
    if args.sample:
        qs = stratified_sample(qs, args.sample)
    if not qs:
        sys.exit("no questions match")

    solver = get_solver(args.solver)
    name = args.name or f"{args.solver.replace('@', '-')}_{args.split}_{time.strftime('%Y%m%d-%H%M%S')}"
    Path("runs").mkdir(exist_ok=True)
    out_path = Path("runs") / f"{name}.jsonl"

    def run(q):
        t0 = time.time()
        try:
            res = solver(q)
        except Exception as e:  # noqa: BLE001  a crash counts as an abstain, and is logged
            res = {"answer": None, "confidence": 0, "evidence": [], "cost_usd": 0.0, "method": "error",
                   "error": repr(e)[:300]}
        dt = time.time() - t0
        return {
            "id": q["id"], "path": q["path"], "source": q["source"], "type": q["type"], "ext": q["ext"],
            "lang": lang_of(q["question"]), "question": q["question"], "gold": q["answer"],
            "pred": res.get("answer"), "correct": is_correct(q["type"], res.get("answer"), q["answer"]),
            "confidence": res.get("confidence"), "cost_usd": float(res.get("cost_usd") or 0.0),
            "latency_s": round(dt, 3), "method": res.get("method"),
            "evidence": res.get("evidence", []), **{k: res[k] for k in ("error", "raw", "turns") if k in res},
        }

    rows = []
    with open(out_path, "w") as f, cf.ThreadPoolExecutor(args.jobs) as ex:
        for i, r in enumerate(ex.map(run, qs), 1):
            rows.append(r)
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
            f.flush()
            if i % max(1, len(qs) // 20) == 0 or i == len(qs):
                ok = sum(1 for x in rows if x["correct"])
                print(f"  {i}/{len(qs)}  acc so far {ok / i:.1%}", file=sys.stderr)

    summary = [f"# {name}", "", f"solver `{args.solver}`, split `{args.split}`, n={len(rows)}"
               + (f", stratified sample {args.sample}" if args.sample else ""), "",
               "accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.", "",
               "## By type", table(rows, lambda r: r["type"]), "",
               "## By source", table(rows, lambda r: r["source"]), "",
               "## By source and type", table(rows, lambda r: f"{r['source']} / {r['type']}"), "",
               "## By language", table(rows, lambda r: r["lang"]), ""]
    text = "\n".join(summary)
    (Path("runs") / f"{name}.summary.md").write_text(text)
    print(text)
    print(f"\nlog: {out_path}")


if __name__ == "__main__":
    main()
