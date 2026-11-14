"""Free-text answers about IFC models from a citable fact sheet + a cheap LLM (haiku).

Variants (`ifctext@<mode>[-<model>]`):
  combo            the rule-based report (bp.ifc.bench) is given to the model as a DRAFT next to the fact
                   sheet; the model replies KEEP (draft returned verbatim, rule evidence) or writes a better
                   answer from the facts.
  llm              fact sheet only, no draft.
  route (default)  rule report for the generators that beat the LLM on dev (TRUSTED_RULES), else llm.
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

VERSION = "v4"
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
- Scope: answer for exactly the scope asked (one level, one room, exterior or interior only, one element kind). \
Do not add other levels, rooms or element kinds the question did not ask about. A question about the building \
covers all levels.
- Lists: when asked which types / items / rooms, list every matching line of the sheet with its count and give the \
total; never shorten a list to "+N more". Group the items the way the question asks (by level, by type, by function).
- "Types" of elements are the type names in the sheet. Levels are the IfcBuildingStorey names. Generic IFC2x3 \
classes are split by kind (IfcFlowTerminal / WasteTerminal, IfcFlowController / Valve, ...): use the kind that \
matches the question (pipe accessories are valves / flow controllers, plumbing fixtures are sanitary terminals).
- Rooms: the ROOM CONTENTS block says which furniture, sanitary items and equipment are located in which space; \
use it for questions about a room's contents or where items are. Site latitude / longitude are in the PROJECT block.
- Areas: when a gross floor area (GFA) is asked and the sheet has no separate gross figure, give the total of the \
space areas per level and overall as the floor area (say it is the sum of the space areas), if the model has \
spaces.
- Sizes: thicknesses come from the material layers (layer thicknesses in mm); when a type name states a nominal \
size (e.g. 'Generic 200 mm', 'STB 20.0', '50cm') and no layers are given, report the nominal size from the name.
- Structural elements / structural system: columns, beams, slabs (floor / roof / base slab split), members, \
plates, footings and piles; count walls as structural only if they are marked load-bearing.
- When asked what something means or is, give its meaning briefly next to the value.
- Format: a compact structured report: a title line, then "- name: value" bullet lines. No preamble, no markdown \
headers or bold, no caveats unless essential.
- Before saying something is not available, look again: type names, instance names, space names, kinds and \
properties often hold the answer (a material, function, size or level is often part of a name). Answer the parts \
you can directly; do not lead with "not available" when the sheet answers most of the question.
- If the sheet shows that the model has no elements of the asked kind, say so directly ("There are no ... in the \
model.").
- If the sheet does not contain the information at all, reply "This information is not available in the BIM \
model."{estimate}
- Finish with one last line "FACTS: f3, f17, ..." listing the ids of the fact lines your answer is based on \
(or "FACTS: none")."""

EST_YES = """ The question asks for an estimate, typical values or an inference, so in that case add \
"However, a rough estimate:" and give one brief estimate derived from the facts or from standard practice, marked as an estimate."""
EST_NO = """ Do not add estimates, typical values or guesses in that case."""
ESTIMATE_Q = re.compile(r"estimat|approx|typical|likely|probabl|rough|expected|assum|possible|potential|"
                        r"if (?:this|the|it)[\w ]* not (?:directly )?available|determine|infer|suggest|concept|assessment|"
                        r"recyclab|kind of|what type of (?:roof|structur|foundation|heating|construction)", re.I)

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
        parts = (variant or "route").split("-")
        self.mode = parts[0]
        # answering model: `ifctext@route-sonnet`, or BP_IFCTEXT_MODEL=sonnet for the router's default ifctext
        # (default haiku; on a 300-question dev sample sonnet was -0.3 pp at ~9x the cost, see docs/IFCTEXT.md)
        self.model = parts[1] if len(parts) > 1 else os.environ.get("BP_IFCTEXT_MODEL", "haiku")
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

        from bp.ifc.bench import find_space

        st = find_storey(m, q["question"])
        sp = find_space(m, q["question"])
        facts, used = render(blocks, q["question"], self.budget, focus={st["name"]} if st else None,
                             space=sp.get("name") if sp else None)
        guids = {fid: g for b in blocks for fid, g in b["guids"].items()}
        lines = {fid: t for b in blocks for fid, t in b["lines"] if fid}
        use_draft = self.mode == "combo"
        prompt = f"FACT SHEET ({Path(rel).name}):\n{facts}\n\n"
        if use_draft:
            prompt += f"DRAFT:\n{draft['answer']}\n\n"
        prompt += f"QUESTION: {q['question']}"
        system = SYSTEM.replace("{estimate}", EST_YES if ESTIMATE_Q.search(q["question"]) else EST_NO) \
            + (DRAFT_RULES if use_draft else "")
        key = _hash(VERSION, self.model, system, prompt)
        f = CACHE / f"{key[:2]}/{key}.json"
        if f.exists():
            res = json.loads(f.read_text())
            res["cached"] = True  # report the real per-question cost even when replayed from cache
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
        out = {"answer": text, "confidence": 0.3 if na else 0.6, "method": f"ifctext-{self.mode}-{self.model}",
               "cost_usd": cost, "evidence": ev, "facts_cited": cited,
               "explanation": f"{self.model} answer from the fact sheet ({len(facts)} chars, "
                              f"{len(used)} blocks), citing {len(cited)} facts"}
        # provenance: every number / quoted name must be in a cited fact line (or derived from them)
        from bp import provenance

        prov = provenance.check(text, [(fid, lines[fid]) for fid in dict.fromkeys(cited) if fid in lines],
                                context=[ln if ln.startswith("[f") else ("sheet", ln) for ln in facts.splitlines()])
        ok = provenance.verified_sources(prov)
        for e in ev:
            if e["label"][1:].split("]")[0] in ok:
                e["verified"] = True
        return provenance.apply(out, prov)


def _trust_rules(draft: dict) -> bool:
    """Route to the rule report for the generators that beat the LLM on the dev split by >= 2 questions."""
    return draft.get("method") in TRUSTED_RULES


# dev split (710), judge-correct rules vs llm (n), fact sheet v4 (ifctext_llm_dev_v5): software 12 vs 10 (13),
# largest-room 6 vs 4 (7), coverings 5 vs 4 (6), mep-kind 7 vs 7 (32, kept: deterministic and free).
# room-furniture (rules 2 vs llm 3 of 3) now goes to the LLM, which sees the ROOM CONTENTS block.
TRUSTED_RULES = {"ifc-text-mep-kind", "ifc-text-software", "ifc-text-largest-room", "ifc-text-coverings"}
