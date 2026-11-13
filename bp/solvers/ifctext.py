"""Free-text answers about IFC models from a citable fact sheet + a cheap LLM (haiku).

Variants (`ifctext@<mode>[-<model>]`):
  combo (default)  the rule-based report (bp.ifc.bench) is given to the model as a DRAFT next to the fact
                   sheet; the model replies KEEP (draft returned verbatim, rule evidence) or writes a better
                   answer from the facts.
  llm              fact sheet only, no draft.
  route            rules where the rule generator is confident and on-topic; else combo.
The model cites fact ids (f12, ...); each id maps back to the GlobalIds it was computed from, which become
`ifc` evidence items. Answers are cached on disk (cache/ifctext/), so re-runs are free.
Opening_design PDFs (text questions): bp.ifctext.pdftext builds the sheet from vector text instead.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from bp.data import data_root
from bp.ifctext.llm import ask

VERSION = "v3"
CACHE = Path(os.environ.get("BP_CACHE", "cache")) / "ifctext"
NA = "This information is not available in the BIM model."
MAX_EV_GUIDS = 3000

SYSTEM = """You answer questions about one BIM (IFC) model for construction professionals, using a FACT SHEET \
extracted from the model. Each data line of the sheet has an id like [f12].

Rules:
- Use only the fact sheet (and the DRAFT, if one is given). Never invent elements, names or numbers. You may add \
up, count, compute percentages, averages and differences from the facts.
- Answer exactly what is asked: give the requested numbers (counts; areas in sq m; lengths and heights in m; \
thicknesses and widths in mm), the names (types, rooms, levels, materials) exactly as written in the model, and \
totals / per-level distributions / percentages when the question asks for them.
- "Types" of elements are the type names in the sheet. Levels are the IfcBuildingStorey names.
- Format: a compact structured report: a title line, then "- name: value" bullet lines. No preamble, no markdown \
headers or bold, no caveats unless essential.
- Before saying something is not available, look again: type names, instance names, space names and \
properties often hold the answer (a material, function, size or level is often part of a name).
- If the sheet does not contain the information, reply "This information is not available in the BIM model." \
optionally followed by one sentence on what related data the model does contain.
- Finish with one last line "FACTS: f3, f17, ..." listing the ids of the fact lines your answer is based on \
(or "FACTS: none")."""

DRAFT_RULES = """
A DRAFT answer produced by deterministic keyword rules is also given. It is usually right when it addresses the \
question, but it can be off-topic (answers a different question), incomplete, or claim "not available" wrongly. \
If the DRAFT fully and correctly answers the question, reply with only "KEEP" on the first line and then the \
FACTS line. Otherwise write the corrected answer (reuse the draft's correct parts)."""


def _hash(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, ensure_ascii=False, default=str).encode()).hexdigest()


def parse_reply(text: str):
    """(answer text, cited fact ids, keep?)"""
    text = (text or "").strip()
    facts = []
    m = re.search(r"^\s*FACTS:\s*(.*)$", text, re.M | re.I)
    if m:
        facts = re.findall(r"f\d+", m.group(1))
        text = (text[:m.start()] + text[m.end():]).strip()
    keep = bool(re.fullmatch(r"\**KEEP\**\.?", text.strip(), re.I))
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.M)
    return text.strip(), facts, keep


class IfcTextSolver:
    def __init__(self, variant=None, budget: int = 14000):
        parts = (variant or "combo").split("-")
        self.mode = parts[0]
        self.model = parts[1] if len(parts) > 1 else "haiku"
        self.budget = budget
        self._sheets = {}

    # ------------------------------------------------------------------ IFC
    def sheet(self, rel: str, m):
        if rel not in self._sheets:
            from bp.ifctext.factsheet import build

            self._sheets[rel] = build(m)
        return self._sheets[rel]

    def __call__(self, q: dict) -> dict:
        if q["path"].lower().endswith(".pdf") and q.get("source") != "ifc_models":
            from bp.ifctext.pdftext import answer_pdf

            return answer_pdf(q, self.model)
        from bp.ifc.extract import load_model
        from bp.solvers.ifc import ifc_path_for

        rel, ifc = ifc_path_for(q["path"])
        if not ifc.exists():
            return {"answer": None, "confidence": 0.0, "method": "ifctext", "cost_usd": 0.0, "evidence": [],
                    "explanation": f"IFC model {rel} not available"}
        m = load_model(ifc)
        from bp.ifc.bench import answer_text

        draft = answer_text(m, q, rel)
        if self.mode == "rules":
            return draft
        if self.mode == "route" and _trust_rules(draft):
            return {**draft, "method": draft["method"] + "+route"}
        blocks = self.sheet(rel, m)
        from bp.ifctext.factsheet import render

        from bp.ifc.bench import find_storey

        st = find_storey(m, q["question"])
        facts, used = render(blocks, q["question"], self.budget, focus={st["name"]} if st else None)
        guids = {fid: g for b in blocks for fid, g in b["guids"].items()}
        lines = {fid: t for b in blocks for fid, t in b["lines"] if fid}
        use_draft = self.mode in ("combo", "route")
        prompt = f"FACT SHEET ({Path(rel).name}):\n{facts}\n\n"
        if use_draft:
            prompt += f"DRAFT:\n{draft['answer']}\n\n"
        prompt += f"QUESTION: {q['question']}"
        system = SYSTEM + (DRAFT_RULES if use_draft else "")
        key = _hash(VERSION, self.model, system, prompt)
        f = CACHE / f"{key[:2]}/{key}.json"
        if f.exists():
            res = json.loads(f.read_text())
            res["cost_usd_cached"], res["cost_usd"] = res["cost_usd"], 0.0
        else:
            res = ask(prompt, system, self.model, tag=f"ifctext-{self.mode}")
            if not res.get("error"):
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(json.dumps(res, ensure_ascii=False))
        if res.get("error") or not res.get("text"):
            return {**draft, "method": draft["method"] + "+llm-error", "cost_usd": res.get("cost_usd", 0.0)}
        text, cited, keep = parse_reply(res["text"])
        cost = res.get("cost_usd", 0.0)
        if keep and use_draft:
            return {**draft, "method": f"ifctext-keep-{self.model}", "cost_usd": cost,
                    "facts_cited": cited, "explanation": "rule-based report confirmed by the model against the fact sheet"}
        ev = []
        for fid in dict.fromkeys(cited):
            if fid in guids:
                ev.append({"kind": "ifc", "file": rel, "guids": guids[fid][:MAX_EV_GUIDS],
                           "label": f"[{fid}] {lines[fid][:160]}", "value": len(guids[fid])})
        na = text.startswith(NA[:30])
        return {"answer": text, "confidence": 0.3 if na else 0.6, "method": f"ifctext-{self.mode}-{self.model}",
                "cost_usd": cost, "evidence": ev, "facts_cited": cited,
                "explanation": f"{self.model} answer from the fact sheet ({len(facts)} chars, "
                               f"{len(used)} blocks), citing {len(cited)} facts"}


def _trust_rules(draft: dict) -> bool:
    """Rule reports that dev-split judging found reliable (see bp/ifctext/README-free notes in the report)."""
    return draft.get("method") in TRUSTED_RULES


# filled from the dev-split per-method judge accuracy of the rule solver (rules >= 70 % correct, n >= 5)
TRUSTED_RULES: set = set()
