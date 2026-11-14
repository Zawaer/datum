"""Typed-question stress test: questions a judge might type themselves (not dataset templates).

Set: analysis/typed_questions.jsonl (65 questions on 9 TEST-split drawings: 4 Swiss PDFs, 3 CubiCasa PNGs,
2 IFC models). Each item carries the expected behaviour ("answer" with a gold derived from the dataset's answer
to the equivalent template question or from the IFC/DXF data checked with ifcopenshell, or "decline") and a
category (casual, typo, units, language, yes/no, comparative, multi-part, out-of-scope).

Run: .venv/bin/python analysis/typed_eval.py [--tag NAME]   -> runs/typed_<tag>.jsonl + a table on stdout.
The router is called like the app calls it (type = guess_type(question)); the Haiku normaliser is on.

Verdicts: correct / wrong answer / honest decline (expected decline, or an ambiguous question where asking back
is acceptable) / bad decline (abstained on a question the drawing answers).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("BP_CROSSCHECK", "0")

from bp.router import Router, guess_type  # noqa: E402
from bp.score import REL_TOL, to_number  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SET = ROOT / "analysis/typed_questions.jsonl"
NUM = re.compile(r"-?\d+(?:[.,]\d+)?")


def numbers(x) -> list[float]:
    return [float(m.replace(",", ".")) for m in NUM.findall(str(x).replace(" ", "").replace("'", ""))]


def close(p, g, tol=REL_TOL) -> bool:
    return g == 0 and abs(p) < 1e-9 or g != 0 and abs(p - g) / abs(g) <= tol


# a text answer that only says the drawing does not hold the information is a decline, not an answer
DECLINE = re.compile(r"^\s*this information is not available", re.I)


def verdict(it, pred) -> str:
    if pred is not None and DECLINE.match(str(pred)):
        pred = None
    if it["expect"] == "decline":
        return "honest decline" if pred is None else "wrong answer"
    if pred is None:
        return "honest decline" if it["accept_decline"] else "bad decline"
    k, g = it["kind"], it["gold"]
    if k == "count":
        p = to_number(pred)
        ok = p is not None and round(p) == g and abs(p - round(p)) < 1e-6
    elif k in ("area", "length"):
        p = to_number(pred)
        ok = p is not None and close(p, g)
    elif k == "multi":  # every asked number must be in the answer
        ns = numbers(pred)
        ok = all(any(abs(n - x) < 1e-6 for n in ns) for x in g)
    elif k == "yesno":
        s = str(pred).strip().lower()
        if re.match(r"(yes|ja|kyllä|oui|sí|si)\b", s):
            ok = g["yes"]
        elif re.match(r"(no|nein|ei|non)\b", s):
            ok = not g["yes"]
        else:  # a count answers "any X?" (1 bathtub = yes)
            p = to_number(pred)
            ok = "count" in g and p is not None and round(p) == g["count"]
    elif k == "text":
        ok = any(t.lower() in str(pred).lower() for t in g)
    else:
        ok = False
    return "correct" if ok else "wrong answer"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="after")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--fresh", action="store_true",
                    help="ignore the normaliser cache (a scratch cache in /tmp): measures run-to-run stability")
    ap.add_argument("--rescore", help="only re-score an existing runs/typed_<tag>.jsonl with the current set")
    args = ap.parse_args()
    items = [json.loads(l) for l in open(SET)]
    if args.rescore:
        old = {r["n"]: r for r in map(json.loads, open(ROOT / f"runs/typed_{args.rescore}.jsonl"))}
        report([{**old[it["n"]], **it, "verdict": verdict(it, old[it["n"]]["pred"])} for it in items], None)
        return
    if args.fresh:
        import tempfile

        import bp.normalize as N
        N.CACHE, N._mem = Path(tempfile.mkdtemp()) / "normalize.jsonl", None
    router = Router()

    def one(it):
        q = {"id": -1, "path": it["path"], "source": it["source"], "ext": it["path"].rsplit(".", 1)[-1],
             "question": it["question"], "type": guess_type(it["question"]), "answer": None}
        try:
            res = router(q)
        except Exception as e:  # noqa: BLE001
            res = {"answer": None, "explanation": f"crash: {e!r}"[:200]}
        pred = res.get("answer")
        return {**it, "type": q["type"], "pred": pred, "confidence": res.get("confidence"),
                "route": res.get("route"), "method": res.get("method"),
                "normalized_question": res.get("normalized_question"),
                "normalize_why": (res.get("normalize") or {}).get("why"),
                "explanation": str(res.get("explanation") or "")[:300],
                "cost_usd": float(res.get("cost_usd") or 0.0), "verdict": verdict(it, pred)}

    with ThreadPoolExecutor(args.jobs) as ex:
        rows = list(ex.map(one, items))
    out = ROOT / f"runs/typed_{args.tag}.jsonl"
    with open(out, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    report(rows, out)


def report(rows, out):

    V = ["correct", "wrong answer", "honest decline", "bad decline"]
    by = defaultdict(Counter)
    for r in rows:
        by[r["category"]][r["verdict"]] += 1
        by[r["source"]][r["verdict"]] += 1
        by["ALL"][r["verdict"]] += 1
    print("| group | n | " + " | ".join(V) + " |\n|---|---|" + "---|" * len(V))
    for g, c in by.items():
        print(f"| {g} | {sum(c.values())} | " + " | ".join(str(c[v]) for v in V) + " |")
    print(f"\ncost ${sum(r['cost_usd'] for r in rows):.4f}" + (f"  -> {out}" if out else "") + "\n")
    for r in rows:
        if r["verdict"] in ("wrong answer", "bad decline"):
            print(f"[{r['verdict']}] {r['source'][:6]} {r['category']}: {r['question']!r} gold={r['gold']} "
                  f"pred={str(r['pred'])[:80]!r} read_as={r['normalized_question']!r} | {r['explanation'][:160]}")


if __name__ == "__main__":
    main()
