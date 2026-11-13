"""LLM judge for free-text answers (replaces the token-F1 proxy when eval.py runs with --judge).

    from bp.judge import judge
    judge(question, gold, pred) -> {"correct": bool, "score": 0..1, "reason": str, "cost_usd": float}

A cheap model (haiku) compares the prediction to the reference answer with a fixed rubric. Verdicts are
cached on disk (cache/judge/<sha1(rubric version, model, q, gold, pred)>.json), so re-scoring a run is free.
Validation against hand labels: `python -m bp.judge --validate` (labels: bp/ifctext/judge_labels.json).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from bp.ifctext.llm import ask

MODEL = os.environ.get("BP_JUDGE_MODEL", "haiku")
VERSION = "v2"
CACHE = Path(os.environ.get("BP_CACHE", "cache")) / "judge"

SYSTEM = """You grade answers to questions about building drawings and BIM (IFC) models against a reference answer.

Decide whether the PREDICTION gives the user the same answer as the REFERENCE for what the QUESTION asks.

Rules:
- Identify the key facts in the REFERENCE that answer the question: numbers (counts, areas, lengths, heights, \
percentages, totals) and named items (rooms, types, materials, levels, software).
- Numbers: counts must match exactly; measures may differ by up to 2 % or by rounding to fewer decimals \
(4.7 vs 4.72 is fine, 476 vs 275 is not). Units may differ if the values convert (1730 mm = 1.73 m).
- Names: the same items must be named; wording, language, order, case and formatting may differ \
("Inline Pump" = "Inline Pumpe"; an item split into sub-types whose counts add up to the reference count is fine).
- Extra correct detail is fine. Omitting background detail the question did not ask for (timestamps, \
percentages, notes) is fine. Omitting or getting wrong a part the question explicitly asks for \
(e.g. the per-floor distribution, a list of items, a total) is NOT fine.
- Contradicting a key fact is wrong, even if other parts are right. Listing many items that are not in the \
reference, when the question asks about a specific subset, is wrong.
- If the REFERENCE says the information is not available and the PREDICTION says so too (any wording) -> correct. \
If the REFERENCE gives a value (or a probable estimate) and the PREDICTION says it is not available, or gives a \
different value -> wrong.
- When the reference has several key facts, the prediction is correct only if essentially all of them are right \
(at most one minor slip in a long list).

Reply with one line of JSON only: {"score": <fraction of key facts right, 0..1>, "correct": true|false, \
"reason": "<one short sentence>"}"""


def _key(question, gold, pred) -> str:
    return hashlib.sha1(json.dumps([VERSION, MODEL, question, gold, pred], ensure_ascii=False,
                                   default=str).encode()).hexdigest()


def _clip(s, n=6000):
    s = str(s)
    return s if len(s) <= n else s[:n] + f"\n...[{len(s) - n} more characters]"


def judge(question: str, gold, pred) -> dict:
    if isinstance(gold, list):
        gold = ", ".join(map(str, gold))
    if pred is None or str(pred).strip() == "":
        return {"correct": False, "score": 0.0, "reason": "no answer", "cost_usd": 0.0, "cached": True}
    k = _key(question, gold, pred)
    f = CACHE / f"{k[:2]}/{k}.json"
    if f.exists():
        r = json.loads(f.read_text())
        r["cost_usd"], r["cached"] = 0.0, True
        return r
    prompt = f"QUESTION:\n{question}\n\nREFERENCE:\n{_clip(gold)}\n\nPREDICTION:\n{_clip(pred)}"
    res = ask(prompt, SYSTEM, MODEL, tag="judge")
    r = _parse(res.get("text", ""))
    if r is None:
        return {"correct": False, "score": 0.0, "reason": f"judge error: {res.get('error') or res.get('text', '')[:200]}",
                "cost_usd": res["cost_usd"], "error": True}
    r["cost_usd"] = res["cost_usd"]
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(r, ensure_ascii=False))
    r["cached"] = False
    return r


def _parse(text: str):
    """The last flat {...} in the reply that parses as JSON with a 'correct' key."""
    d = None
    for m in re.finditer(r"\{[^{}]*\}", text):
        try:
            c = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(c, dict) and "correct" in c:
            d = c
    if d is None:
        return None
    try:
        score = float(d.get("score", 1.0 if d.get("correct") else 0.0))
    except (TypeError, ValueError):
        score = 0.0
    correct = d.get("correct")
    if isinstance(correct, str):
        correct = correct.strip().lower() == "true"
    return {"correct": bool(correct), "score": max(0.0, min(1.0, score)), "reason": str(d.get("reason", ""))[:300]}


# ---------------------------------------------------------------- validation
LABELS = Path(__file__).parent / "ifctext" / "judge_labels.json"


def validate(jobs: int = 8):
    """Agreement of judge and proxy with the hand labels (gold/question joined from the dataset by id)."""
    import concurrent.futures as cf

    from bp.data import load_questions
    from bp.score import is_correct

    qs = {q["id"]: q for q in load_questions()}
    labels = json.loads(LABELS.read_text())
    items = [(lab, qs[lab["id"]]) for lab in labels]
    with cf.ThreadPoolExecutor(jobs) as ex:
        verdicts = list(ex.map(lambda it: judge(it[1]["question"], it[1]["answer"], it[0]["pred"]), items))
    stats = {"judge": [0, 0], "proxy": [0, 0], "judge_clear": [0, 0], "proxy_clear": [0, 0]}
    cost = 0.0
    for (lab, q), v in zip(items, verdicts):
        cost += v["cost_usd"]
        p = bool(is_correct(q["type"], lab["pred"], q["answer"]))
        for name, val in (("judge", v["correct"]), ("proxy", p)):
            stats[name][0] += val == lab["label"]
            stats[name][1] += 1
            if not lab.get("ambiguous"):
                stats[name + "_clear"][0] += val == lab["label"]
                stats[name + "_clear"][1] += 1
        if v["correct"] != lab["label"]:
            print(f"  DISAGREE id={lab['id']} ({lab.get('note', '')}) label={lab['label']} judge={v['correct']} "
                  f"amb={lab.get('ambiguous', False)}: {v['reason']}")
    for k, (a, n) in stats.items():
        print(f"{k:12s} {a}/{n} = {a / max(n, 1):.1%}")
    print(f"judge cost this run: ${cost:.4f}")
    return stats


if __name__ == "__main__":
    import sys

    if "--validate" in sys.argv:
        validate()
