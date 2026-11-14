"""Robustness extras: language-twin agreement, paraphrases, must-abstain questions.

    .venv/bin/python analysis/robustness.py twins            # agreement across language twins (no compute)
    .venv/bin/python analysis/robustness.py para-gen         # ~150 English paraphrases via Claude Haiku (CLI)
    .venv/bin/python analysis/robustness.py para-run         # router on originals + paraphrases
    .venv/bin/python analysis/robustness.py abstain-run      # router on ~50 unanswerable questions
    .venv/bin/python analysis/robustness.py report           # -> docs/ROBUSTNESS.md

Files: runs/robustness_twins.jsonl, runs/robustness_paraphrases.jsonl (generated questions),
runs/robustness_paraphrase_run.jsonl, runs/robustness_abstain.jsonl. All on the TEST split.
"""
import collections
import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bp.data import load_questions  # noqa: E402
from bp.score import is_correct  # noqa: E402

RUN = ROOT / "runs/router_full_test_v4.jsonl"
TWINS = ROOT / "runs/robustness_twins.jsonl"
PARA = ROOT / "runs/robustness_paraphrases.jsonl"
PARA_RUN = ROOT / "runs/robustness_paraphrase_run.jsonl"
ABST = ROOT / "runs/robustness_abstain.jsonl"
DOC = ROOT / "docs/ROBUSTNESS.md"


def h(s):
    return int(hashlib.sha1(s.encode()).hexdigest()[:12], 16)


def load_run():
    return [json.loads(l) for l in open(RUN)]


def same_answer(qtype, a, b):
    if a is None or b is None:
        return a is None and b is None
    if qtype in ("text", "other"):
        return str(a).strip() == str(b).strip()
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return str(a) == str(b)
    return abs(fa - fb) <= 1e-6 + 0.005 * max(abs(fa), abs(fb))


# ------------------------------------------------------------------ 1. language twins
def twins():
    """Pair every non-English question with its English twin (same drawing, same gold, adjacent in the
    dataset). Twins are free paraphrases: the router must give the same answer to both."""
    rows = {r["id"]: r for r in load_run()}
    out = []
    for i, r in rows.items():
        if r["lang"] == "en":
            continue
        for j in (i - 1, i + 1):
            e = rows.get(j)
            if e and e["lang"] == "en" and e["path"] == r["path"] and e["type"] == r["type"] \
                    and json.dumps(e["gold"]) == json.dumps(r["gold"]):
                out.append({"source": r["source"], "type": r["type"], "lang": r["lang"], "id_en": j, "id_x": i,
                            "q_en": e["question"], "q_x": r["question"], "pred_en": e["pred"], "pred_x": r["pred"],
                            "correct_en": bool(e["correct"]), "correct_x": bool(r["correct"]),
                            "agree": same_answer(r["type"], e["pred"], r["pred"])})
                break
    with open(TWINS, "w") as f:
        for o in out:
            f.write(json.dumps(o, ensure_ascii=False, default=str) + "\n")
    print(f"{len(out)} twin pairs -> {TWINS}")


# ------------------------------------------------------------------ 2. paraphrases
QUOTA = {("cubicasa5k", "count"): 60, ("swiss_dwellings", "count"): 24, ("swiss_dwellings", "area"): 21,
         ("ifc_models", "count"): 12, ("ifc_models", "area"): 8, ("ifc_models", "volume"): 4,
         ("ifc_models", "length"): 3, ("ifc_bench", "text"): 18}

PARA_SYSTEM = """You rewrite questions about building drawings so that they are worded differently but mean \
exactly the same thing. For each input question write ONE paraphrase that a real user might type:
- change the wording and sentence structure (synonyms, different order, more casual or more formal);
- keep the meaning IDENTICAL: same object class, same counting rules / exclusions / inclusions, same unit;
- copy every quoted name, room number, apartment letter, storey name, model name and number EXACTLY, \
inside the same kind of quotes;
- do not add or drop any condition, do not answer the question.
Reply with JSON only: a list of {"i": <index>, "p": "<paraphrase>"} in the input order."""


def template_key(q):
    return re.sub(r"'[^']*'|\d+(?:\.\d+)?|apartment [A-Z]\b", "X", q)[:80]


def pick_originals():
    rows = [r for r in load_run() if r["lang"] == "en"]
    out = []
    for (src, typ), n in QUOTA.items():
        g = [r for r in rows if r["source"] == src and r["type"] == typ]
        by_t = collections.defaultdict(list)
        for r in g:
            by_t[template_key(r["question"])].append(r)
        for v in by_t.values():
            v.sort(key=lambda r: h(f"{r['path']}|{r['question']}"))
        keys = sorted(by_t, key=lambda k: -len(by_t[k]))
        i = 0
        picked = []
        while len(picked) < n and any(i < len(by_t[k]) for k in keys):
            for k in keys:
                if i < len(by_t[k]) and len(picked) < n:
                    picked.append(by_t[k][i])
            i += 1
        out += picked
    return out


def para_gen():
    """One question per Haiku call (batched calls mis-aligned paraphrases with their originals)."""
    from concurrent.futures import ThreadPoolExecutor

    from bp.ifctext.llm import ask
    orig = pick_originals()

    def one(r):
        res = ask(f"0. {r['question']}", PARA_SYSTEM, "haiku", tag="robustness-paraphrase")
        m = re.search(r"\[.*\]", res.get("text", ""), re.S)
        try:
            items = json.loads(m.group(0)) if m else []
        except json.JSONDecodeError:
            items = []
        p = items[0].get("p", "").strip() if items and isinstance(items[0], dict) else ""
        return r, p, res.get("cost_usd", 0.0)

    cost, out = 0.0, []
    with ThreadPoolExecutor(6) as ex:
        for r, p, c in ex.map(one, orig):
            cost += c
            if p:
                out.append({"id": r["id"], "source": r["source"], "type": r["type"], "path": r["path"],
                            "question": r["question"], "paraphrase": p, "gold": r["gold"]})
    with open(PARA, "w") as f:
        for o in out:
            f.write(json.dumps(o, ensure_ascii=False, default=str) + "\n")
    print(f"{len(out)} paraphrases -> {PARA}, generation cost ${cost:.4f}")


def _solve(router, q):
    t0 = time.time()
    try:
        res = router(q)
    except Exception as e:  # noqa: BLE001
        res = {"answer": None, "confidence": 0.0, "method": "error", "explanation": repr(e)[:200], "evidence": []}
    return {"pred": res.get("answer"), "confidence": res.get("confidence"), "method": res.get("method"),
            "explanation": res.get("explanation"), "n_evidence": len(res.get("evidence") or []),
            "cost_usd": float(res.get("cost_usd") or 0.0), "latency_s": round(time.time() - t0, 2)}


def para_run():
    from bp.router import Router
    router = Router()
    qs = {q["id"]: q for q in load_questions()}
    paras = [json.loads(l) for l in open(PARA)]
    with open(PARA_RUN, "w") as f:
        for i, p in enumerate(paras):
            q = qs[p["id"]]
            o = _solve(router, q)
            qp = dict(q, question=p["paraphrase"])
            pp = _solve(router, qp)
            row = {**p, "orig": o, "para": pp,
                   "correct_orig": is_correct(q["type"], o["pred"], q["answer"]),
                   "correct_para": is_correct(q["type"], pp["pred"], q["answer"])}
            if q["type"] in ("text", "other"):
                from bp.judge import judge
                for k in ("orig", "para"):
                    if row[k]["pred"] is not None:
                        v = judge(q["question"], q["answer"], row[k]["pred"])
                        row[f"correct_{k}"] = v["correct"]
                        row[k]["judge_cost_usd"] = v.get("cost_usd", 0.0)
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            f.flush()
            if i % 10 == 0:
                print(f"{i}/{len(paras)}", file=sys.stderr)
    print(f"-> {PARA_RUN}")


# ------------------------------------------------------------------ 3. must-abstain
def abstain_set():
    """~50 questions whose honest answer is 'not on this drawing'. Built on test-split drawings."""
    qs = [q for q in load_questions() if q["split"] == "test"]

    def first(src, ext=None, n=1, pred=None):
        g = sorted({q["path"] for q in qs if q["source"] == src and (ext is None or q["ext"] == ext)
                    and (pred is None or pred(q))}, key=h)
        return [g[i % len(g)] for i in range(n)]  # few test IFC sheets / models: reuse drawings

    def base(path):
        q = next(q for q in qs if q["path"] == path)
        return {k: q[k] for k in ("path", "source", "ext", "split")}

    out = []

    def add(path, question, kind):
        out.append({**base(path), "question": question, "kind": kind})

    cc = first("cubicasa5k", n=12)
    cc_qs = ["How many elevators are shown on this floor plan?",
             "How many parking spaces are on this floor plan?",
             "How many swimming pools are on this floor plan?",
             "How many fire extinguishers are drawn on this floor plan?",
             "Kuinka monta hissiä pohjapiirustuksessa on?",
             "How many unicorns are on this floor plan?",
             "What is the ceiling height of the living room in metres?",
             "How many escalators does this floor plan show?",
             "How many hospital beds are drawn on this floor plan?",
             "What is the asking price of this apartment in euros?",
             "How many solar panels are on the roof?",
             "How many tennis courts are on this floor plan?"]
    for p, q in zip(cc, cc_qs):
        add(p, q, "absent object / not drawn" if "price" not in q and "height" not in q else "information not on drawing")

    sw = first("swiss_dwellings", ext="pdf", n=12)
    sw_qs = ["What is the net floor area of room 9.99 ('Zimmer') in m²?",
             "What is the net floor area of apartment Z in m², summing all its rooms except balconies, loggias, "
             "terraces and other outdoor spaces?",
             "How many elevators are drawn on this floor plan?",
             "What is the net floor area of room 77.7 ('Bad') in m²?",
             "How many fireplaces are drawn on this floor plan?",
             "What is the net floor area of apartment Q in m², summing all its rooms except balconies, loggias, "
             "terraces and other outdoor spaces?",
             "How many parking spaces are drawn on this floor plan?",
             "What is the net floor area of room X.42 ('Küche') in m²?",
             "How many unicorns are drawn on this floor plan?",
             "What year was this building built?",
             "How many dishwashers are drawn on this floor plan?",
             "What is the rent of apartment A per month?"]
    for p, q in zip(sw, sw_qs):
        add(p, q, "room/apartment not on plan" if re.search(r"room|apartment Z|apartment Q", q) and "rent" not in q
            else ("information not on drawing" if re.search("year|rent", q) else "absent object / not drawn"))

    ifc = first("ifc_models", ext="pdf", n=12, pred=lambda q: "_plan-" in q["path"])
    models = {}
    for q in qs:
        m = re.search(r"in the model '(.+)'\?", q["question"])
        if m and q["source"] == "ifc_models":
            models[q["path"].split("_plan-")[0]] = m.group(1)
    ifc_qs = ["How many doors are shown on the floor plan of 'Level 99'?",
              "How many windows are shown on the floor plan of '17. Obergeschoss'?",
              "What is the net floor area of the room 'Ballroom (999)' on 'Level 99', in m²?",
              "How many elevators are there in the model '{m}'?",
              "What is the total length of all walls on 'Roof Garden Level 42', in metres?",
              "How many rooms (spaces) are shown on the floor plan of 'Basement -7'?",
              "What is the total net volume of all slabs on 'Mezzanine Z', in m³?",
              "How many swimming pools are there in the model '{m}'?",
              "How many unicorns are there in the model '{m}'?",
              "What is the total net floor area of all rooms (spaces) on 'Level 99', in m²?",
              "How many walls are shown on the floor plan of 'Floor 123'?",
              "What was the construction cost of the model '{m}' in euros?"]
    for p, q in zip(ifc, ifc_qs):
        m = models.get(p.split("_plan-")[0], "this building")
        add(p, q.format(m=m), "storey/room not in model" if re.search(r"99|17\.|42|-7|Mezzanine|123", q)
            else ("information not in model" if "cost" in q else "absent element type"))

    ib = first("ifc_bench", n=14)
    ib_qs = ["What is the name of the architect's dog?",
             "What will the building's electricity bill be in 2030?",
             "How many unicorns are in the building?",
             "What is the phone number of the site manager?",
             "On which day of the week was the concrete for level 3 poured?",
             "What is the market value of the penthouse?",
             "Which football team does the owner support?",
             "How many elevators are on level 99?",
             "What is the WiFi password of the building?",
             "What colour is the CEO's car parked in the garage?",
             "How many people lived here in 1850?",
             "What is the room number of the swimming pool on level 99?",
             "Who won the architectural competition for this building in 1720?",
             "What is the average monthly rent per square metre?"]
    for p, q in zip(ib, ib_qs):
        add(p, q, "information not in model / nonsense")
    return out


NOT_AVAIL = re.compile(r"not (?:available|present|shown|drawn|found|on th|in th|containe|includ|specified|provided|"
                       r"recorded|stored|possible|part of|defined|exist)|no (?:such|information|data|record|"
                       r"\w+ (?:is|are) (?:shown|drawn|present|listed|defined|modelled|modeled))|"
                       r"does(?:n't| not) (?:exist|contain|include|have|record|store|list|show)|cannot|can't|"
                       r"unknown|n/a|unable|isn't|aren't|none (?:are|is|of)|lacks?\b|outside the scope|no \w+ in the",
                       re.I)


def abstain_run():
    from bp.router import Router, guess_type
    router = Router()
    items = abstain_set()
    with open(ABST, "w") as f:
        for it in items:
            q = dict(it, type=guess_type(it["question"]), id=-1, answer=None)
            r = _solve(router, q)
            pred = r["pred"]
            if pred is None:
                verdict = "abstained (answer=None)"
            elif isinstance(pred, str) and NOT_AVAIL.search(pred):
                verdict = "said not available"
            else:
                verdict = "answered"
            f.write(json.dumps({**it, "type": q["type"], **r, "verdict": verdict}, ensure_ascii=False,
                               default=str) + "\n")
            print(verdict, "|", it["source"], "|", it["question"][:70], "|", str(pred)[:80], file=sys.stderr)
    print(f"-> {ABST}")


# ------------------------------------------------------------------ report
FINDINGS = """## Summary

- **Language twins: 100 % agreement** on 12,654 test pairs (Finnish, German, French, Italian, Dutch vs
  English). The templated dataset questions in every language reach the same parse and the same answer.
- **Free English paraphrases: 86.6 % → 58.4 %.** Of 149 Haiku paraphrases, 42 broke an answer that was right
  on the original (none went the other way). 38 of those 42 fail safe: 34 abstain ("question not understood")
  and 4 answer with low confidence (0.3), which the UI shows as "not sure". The other 4 are confident wrong
  answers, all from bug 1 below. The parsers are tuned
  to the dataset's templates. That is fine for the benchmark but brittle for typed questions.
- **Must-abstain: 44/50 correct.** All CubiCasa, Swiss and free-text IFC nonsense or absent-object questions
  abstain or say "not available". The 6 failures are all one IFC bug: an unknown storey name is silently
  ignored (below).

## Bugs found (solver code not changed by this analysis)

1. **Contractions break quoted-slot parsing (IFC and Swiss).** `bp/templates.py` `_Q` treats the apostrophe
   in "What's" as an opening quote, so "What's the number of doors visible on the 'Erdgeschoss' floor plan?"
   yields the slot `s the number of doors visible on the ` and the storey is lost. Swiss `_quoted` is
   greedy (`'(.+)'`) and catches the same text. Effect in the paraphrase run: 8 IFC abstentions, 4 Swiss
   room-area answers of 0 (conf 0.3, "label not found"), and 4 **confident wrong IFC answers**: "What's the
   total count of beams in the '…' model?" → 59 (IfcSpace), "What's the combined net volume … of every wall on
   'Basement'" → 512.7 m³ summed over IfcSlab, conf 0.9. The slot text swallowed the element word, so the
   class fell back to the default. Fix idea: only treat `'` as a quote when it is not between two letters.
2. **IFC: an unknown storey falls back to the whole model.** `bp/solvers/ifc.py::_numeric`: if no slot
   matches a storey, the slot is assumed to be the model name and the answer is model-wide with confidence
   0.9. "How many doors are shown on the floor plan of 'Level 99'?" → 77 (every door in the model);
   "'17. Obergeschoss'" → 110 windows; "'Mezzanine Z'" → 76.99 m³ of slabs. Fuzzy matching also maps
   'Basement -7' to 'Basement' (0 rooms, conf 0.6). Fix idea: abstain when a slot matches neither a storey
   nor the model name (the model name is available in the IFC header / IfcProject).
3. **Swiss: a room label that is not on the plan returns 0, not None** (area_label / count_label, conf 0.3
   / 0.6). For counts, 0 is a defensible answer. For "net area of room 3.29 'Balkon'" parsed as a label
   lookup, it is not.
4. **Template vocabulary.** CubiCasa `bp/cubicasa/questions.py` needs the dataset phrasings: "storeys" without
   "floors (storeys)", "WC bowls", "door openings", "distinct WC rooms" and "What is the total number of doors"
   are not recognised. Swiss needs "labelled", not "marked" or "tagged". These all fail safe (abstain).
"""


def pct(a, b):
    return f"{a / b:.1%}" if b else "-"


def report():
    L = ["# Robustness: language twins, paraphrases, must-abstain", "",
         "Generated by `analysis/robustness.py report`; TEST split only. Run logs: `runs/robustness_*.jsonl`.", "",
         FINDINGS]
    # twins
    T = [json.loads(l) for l in open(TWINS)]
    L += ["## 1. Language twins (free paraphrases)", "",
          "Every non-English test question has an English twin on the same drawing with the same gold answer. "
          "Agreement = the router gives the same answer to both (numbers within 0.5 %; text answers compared "
          "verbatim, which is strict for LLM-written text).", "",
          "| source / type | pairs | same answer | both correct | EN correct | other-language correct |",
          "|---|---|---|---|---|---|"]
    g = collections.defaultdict(list)
    for t in T:
        g[f"{t['source']} / {t['type']}"].append(t)
    for k in sorted(g, key=lambda k: -len(g[k])) + ["ALL"]:
        v = T if k == "ALL" else g[k]
        n = len(v)
        L.append(f"| {'**ALL**' if k == 'ALL' else k} | {n} | {pct(sum(t['agree'] for t in v), n)} | "
                 f"{pct(sum(t['correct_en'] and t['correct_x'] for t in v), n)} | "
                 f"{pct(sum(t['correct_en'] for t in v), n)} | {pct(sum(t['correct_x'] for t in v), n)} |")
    bl = collections.defaultdict(list)
    for t in T:
        bl[t["lang"]].append(t)
    L += ["", "By language of the twin: " + ", ".join(
        f"{k} {pct(sum(t['agree'] for t in v), len(v))} of {len(v)}" for k, v in sorted(bl.items(), key=lambda x: -len(x[1]))) + ".", ""]
    dis = [t for t in T if not t["agree"]]
    if dis:
        L += ["Disagreements (first 8):", ""]
        for t in dis[:8]:
            L.append(f"- {t['source']}: EN `{t['q_en'][:90]}` -> {str(t['pred_en'])[:40]!r}; "
                     f"{t['lang']} `{t['q_x'][:90]}` -> {str(t['pred_x'])[:40]!r}")
        L.append("")
    # paraphrases
    if PARA_RUN.exists():
        P = [json.loads(l) for l in open(PARA_RUN)]
        L += ["## 2. English paraphrases (Claude Haiku)", "",
              f"{len(P)} English test questions, stratified over source, type and question template, each rewritten "
              "once by Claude Haiku (prompt in `analysis/robustness.py`: same meaning, quoted names / numbers copied "
              "exactly). The router answers the original and the paraphrase in the same run with the same code. "
              "Text answers (ifc_bench) are scored by the LLM judge (bp/judge.py), numbers by the official tolerance.",
              "", "| source / type | n | original correct | paraphrase correct | same answer | paraphrase abstained "
              "| paraphrase answered wrong |",
              "|---|---|---|---|---|---|---|"]
        g = collections.defaultdict(list)
        for p in P:
            g[f"{p['source']} / {p['type']}"].append(p)
        for k in sorted(g, key=lambda k: -len(g[k])) + ["ALL"]:
            v = P if k == "ALL" else g[k]
            n = len(v)
            L.append(f"| {'**ALL**' if k == 'ALL' else k} | {n} | {pct(sum(bool(p['correct_orig']) for p in v), n)} | "
                     f"{pct(sum(bool(p['correct_para']) for p in v), n)} | "
                     f"{pct(sum(same_answer(p['type'], p['orig']['pred'], p['para']['pred']) for p in v), n)} | "
                     f"{pct(sum(p['para']['pred'] is None for p in v), n)} | "
                     f"{pct(sum(p['para']['pred'] is not None and not p['correct_para'] for p in v), n)} |")
        lost = [p for p in P if p["correct_orig"] and not p["correct_para"]]
        won = [p for p in P if p["correct_para"] and not p["correct_orig"]]
        L += ["", f"Right on the original but wrong on the paraphrase: {len(lost)}; the reverse: {len(won)}.", ""]
        if lost:
            L += ["Paraphrases that broke the answer:", "", "| source | original | paraphrase | gold | paraphrase answer |",
                  "|---|---|---|---|---|"]
            for p in lost:
                L.append(f"| {p['source']} | {p['question'][:110]} | {p['paraphrase'][:110]} | {str(p['gold'])[:30]} | "
                         f"{str(p['para']['pred'])[:40]} ({p['para']['method']}) |".replace("\n", " "))
            L.append("")
        gen_cost = sum(r["cost_usd"] for r in map(json.loads, open(ROOT / "cache/llm_spend.jsonl"))
                       if r["tag"] == "robustness-paraphrase")
        run_cost = sum(p["orig"]["cost_usd"] + p["para"]["cost_usd"] + p["orig"].get("judge_cost_usd", 0)
                       + p["para"].get("judge_cost_usd", 0) for p in P)
        L += [f"Paid usage: paraphrase generation ${gen_cost:.3f}, solver + judge calls ${run_cost:.3f}.", ""]
    # abstain
    if ABST.exists():
        A = [json.loads(l) for l in open(ABST)]
        L += ["## 3. Must-abstain questions", "",
              f"{len(A)} hand-written questions on test-split drawings whose honest answer is \"not on this drawing\": "
              "objects that are not drawn or not in our vocabulary (elevators on a Finnish single-family plan), storeys "
              "and rooms that do not exist (an IFC storey 'Level 99', Swiss room 9.99, apartment Z), information no "
              "drawing carries (rent, build year, WiFi password) and nonsense (unicorns). Correct behaviour: "
              "answer = None (abstain) or a text answer saying it is not available.", "",
              "| source | n | abstained | said not available | answered anyway |", "|---|---|---|---|---|"]
        g = collections.defaultdict(list)
        for a in A:
            g[a["source"]].append(a)
        for k in sorted(g) + ["ALL"]:
            v = A if k == "ALL" else g[k]
            n = len(v)
            c = collections.Counter(a["verdict"] for a in v)
            L.append(f"| {'**ALL**' if k == 'ALL' else k} | {n} | {pct(c['abstained (answer=None)'], n)} | "
                     f"{pct(c['said not available'], n)} | {pct(c['answered'], n)} |")
        ok = sum(a["verdict"] != "answered" for a in A)
        L += ["", f"Correct behaviour on {ok}/{len(A)} ({pct(ok, len(A))}).", "",
              "Every must-abstain question and what the router did:", "",
              "| source | kind | question | verdict | answer / explanation |", "|---|---|---|---|---|"]
        for a in A:
            ans = a["pred"] if a["pred"] is not None else a.get("explanation")
            L.append(f"| {a['source']} | {a['kind']} | {a['question'][:90]} | {a['verdict']} | "
                     f"{str(ans)[:110]} |".replace("\n", " "))
        L.append("")
    DOC.write_text("\n".join(L))
    print(f"-> {DOC}")


if __name__ == "__main__":
    {"twins": twins, "para-gen": para_gen, "para-run": para_run, "abstain-run": abstain_run,
     "report": report}[sys.argv[1]]()
