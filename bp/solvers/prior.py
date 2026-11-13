"""Dumb baseline: answer every question with the most common dev-split answer
for its template (median for measures). No look at the drawing at all.
Shows how much a solver must beat 'guessing from the question'."""
import collections
import statistics

from bp.data import load_questions
from bp.templates import template


class PriorSolver:
    def __init__(self, variant=None):
        by = collections.defaultdict(list)
        for q in load_questions():
            if q["split"] == "dev":
                by[(q["source"], template(q["question"]))].append(q)
        self.table = {}
        for k, qs in by.items():
            if qs[0]["type"] == "count":
                self.table[k] = collections.Counter(round(float(q["answer"])) for q in qs).most_common(1)[0][0]
            elif qs[0]["type"] in ("area", "length", "volume"):
                self.table[k] = statistics.median(float(q["answer"]) for q in qs)

    def __call__(self, q):
        a = self.table.get((q["source"], template(q["question"])))
        return {"answer": a, "confidence": 0.1, "evidence": [], "cost_usd": 0.0, "method": "prior"}
