"""Robustness extras: language-twin agreement, paraphrases, must-abstain questions.

    .venv/bin/python analysis/robustness.py twins            # agreement across language twins (no compute)
    .venv/bin/python analysis/robustness.py para-gen         # ~150 English paraphrases via Claude Haiku (CLI)
    .venv/bin/python analysis/robustness.py para-gen-fresh   # a second, held-out set: other originals, casual typing
    .venv/bin/python analysis/robustness.py para-run [orig|fresh] [before|after]   # router on originals + paraphrases
    .venv/bin/python analysis/robustness.py abstain-run [before|after]             # router on ~50 unanswerable questions
    .venv/bin/python analysis/robustness.py typed-gen        # ~25 typed room-word / "this floor" questions (no compute)
.venv/bin/python analysis/robustness.py typed-run [before|after]               # router on them, 3 asks each
.venv/bin/python analysis/robustness.py report           # -> docs/ROBUSTNESS.md

"before" = the code before the parser fixes and the question normaliser (commit 9e091b7): run it with
BP_CODE_ROOT=<a checkout of that commit> so `bp` is imported from there.

Files: runs/robustness_twins.jsonl, runs/robustness_paraphrases{,_fresh}.jsonl (generated questions),
runs/robustness_para_{orig,fresh}_{before,after}.jsonl, runs/robustness_abstain_{before,after}.jsonl.
All on the TEST split.
"""
import collections
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.environ.get("BP_CODE_ROOT") or str(ROOT))

from bp.data import load_questions  # noqa: E402
from bp.score import is_correct  # noqa: E402

RUN = ROOT / os.environ.get("BP_TWINS_RUN", "runs/router_full_test_v8.jsonl")
TWINS = ROOT / "runs/robustness_twins.jsonl"
PARA = ROOT / "runs/robustness_paraphrases.jsonl"
PARA_FRESH = ROOT / "runs/robustness_paraphrases_fresh.jsonl"
DOC_BEFORE_RUN = "runs/router_full_test_v4.jsonl"


def para_run_file(which, tag):
    return ROOT / f"runs/robustness_para_{which}_{tag}.jsonl"


def abst_file(tag):
    return ROOT / f"runs/robustness_abstain_{tag}.jsonl"


DOC = ROOT / "docs/ROBUSTNESS.md"


def h(s):
    return int(hashlib.sha1(s.encode()).hexdigest()[:12], 16)


def load_run(path=None):
    """Rows of a run, with `lang` replaced by the one label per question text (see analysis/common.py
    question_lang: eval.py's per-row langdetect tags are not stable across runs)."""
    from common import _detect_lang

    rows = [json.loads(l) for l in open(path or RUN)]
    for r in rows:
        r["lang"] = _detect_lang(r["question"])
    return rows


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


PARA_SYSTEM_FRESH = """You turn questions about building drawings into what a person would actually TYPE into a chat box \
to ask the same thing: casual, often short, everyday words, maybe a contraction or a missing article. For each input \
question write ONE such version:
- keep the meaning IDENTICAL: same object class, same unit, same counting rules (you may shorten long rules to \
their gist, but do not change them);
- keep every quoted name, room number, apartment letter, storey name and model name EXACTLY as written (spelling \
and accents); you may drop the quote marks around them;
- do not answer the question.
Reply with JSON only: a list of {"i": <index>, "p": "<question>"} in the input order."""


def pick_originals(salt=""):
    rows = [r for r in load_run(ROOT / DOC_BEFORE_RUN) if r["lang"] == "en"]  # originals are picked from v4
    out = []
    for (src, typ), n in QUOTA.items():
        g = [r for r in rows if r["source"] == src and r["type"] == typ]
        by_t = collections.defaultdict(list)
        for r in g:
            by_t[template_key(r["question"])].append(r)
        for v in by_t.values():
            v.sort(key=lambda r: h(f"{salt}{r['path']}|{r['question']}"))
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


def para_gen(fresh=False):
    """One question per Haiku call (batched calls mis-aligned paraphrases with their originals)."""
    from concurrent.futures import ThreadPoolExecutor

    from bp.ifctext.llm import ask
    # the fresh set: other originals (salted pick, same quotas; picked from the v4 run like the first set) and a
    # casual-typing prompt. Generated after the fixes were written, never used to change code.
    orig = pick_originals("fresh|" if fresh else "")
    system, tag, outp = (PARA_SYSTEM_FRESH, "robustness-paraphrase-fresh", PARA_FRESH) if fresh else \
        (PARA_SYSTEM, "robustness-paraphrase", PARA)

    def one(r):
        res = ask(f"0. {r['question']}", system, "haiku", tag=tag)
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
    with open(outp, "w") as f:
        for o in out:
            f.write(json.dumps(o, ensure_ascii=False, default=str) + "\n")
    print(f"{len(out)} paraphrases -> {outp}, generation cost ${cost:.4f}")


def _solve(router, q):
    t0 = time.time()
    try:
        res = router(q)
    except Exception as e:  # noqa: BLE001
        res = {"answer": None, "confidence": 0.0, "method": "error", "explanation": repr(e)[:200], "evidence": []}
    return {"pred": res.get("answer"), "confidence": res.get("confidence"), "method": res.get("method"),
            "explanation": res.get("explanation"), "n_evidence": len(res.get("evidence") or []),
            "normalized_question": res.get("normalized_question"), "normalize": res.get("normalize"),
            "cost_usd": float(res.get("cost_usd") or 0.0), "latency_s": round(time.time() - t0, 2)}


def para_run(which="orig", tag="after"):
    from concurrent.futures import ThreadPoolExecutor

    from bp.router import Router
    router = Router()
    qs = {q["id"]: q for q in load_questions()}
    paras = [json.loads(l) for l in open(PARA if which == "orig" else PARA_FRESH)]
    out = para_run_file(which, tag)

    def one(p):
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
        return row

    with open(out, "w") as f, ThreadPoolExecutor(4) as ex:
        for i, row in enumerate(ex.map(one, paras)):
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            f.flush()
            if i % 10 == 0:
                print(f"{i}/{len(paras)}", file=sys.stderr)
    print(f"-> {out}")


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


def abstain_run(tag="after"):
    from bp.router import Router, guess_type
    router = Router()
    items = abstain_set()
    with open(abst_file(tag), "w") as f:
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
    print(f"-> {abst_file(tag)}")


# ------------------------------------------------------------------ 4. typed scope
# Questions a judge types (usability test, app/USABILITY.md): everyday room words on Swiss plans ("How many
# bathrooms?" while the plan says 'Bad'), "this floor" on an IFC plan sheet (that sheet's storey, not the
# building), and "this floor" on the .ifc itself (no storey: must ask which). Built once (`typed-gen`) on test-split
# drawings; gold = the dataset's own answer to the matching template question ("How many rooms labelled 'Bad'
# ...", "How many doors are shown on the floor plan of '<sheet storey>'?"), summed over the plan's labels of
# that kind. Run with the code before (BP_CODE_ROOT=<checkout>) and after: `typed-run before|after`.
TYPED = ROOT / "runs/robustness_typed_scope.jsonl"


def typed_file(tag):
    return ROOT / f"runs/robustness_typed_{tag}.jsonl"


# kept here (not imported from bp/swiss/rooms.py) so the set does not depend on the code it measures
TYPED_KINDS = {
    "bathroom": ({"Bad", "Bain", "Bagno"},
                 ["How many bathrooms are there?", "Wie viele Badezimmer gibt es?",
                  "Combien de salles de bains y a-t-il ?", "how many bathrooms on this floor"]),
    "kitchen": ({"Küche", "Cuisine", "Cucina", "Küche/Essen"},
                ["How many kitchens are on this floor?", "Quante cucine ci sono?"]),
    "bedroom": ({"Schlafzimmer", "Chambre à coucher", "Camera da letto", "Zimmer", "Pièce", "Stanza"},
                ["How many bedrooms are there?", "Combien de chambres sur ce plan ?"]),
    "balcony": ({"Balkon", "Balcon", "Balcone", "Loggia"},
                ["How many balconies does this floor have?", "Wie viele Balkone gibt es?"]),
}
TYPED_IFC = [  # (element key in the dataset template, typed question)
    ("windows", "total window count on this floor"),
    ("doors", "How many doors are on this floor?"),
    ("doors", "Wie viele Türen gibt es auf diesem Geschoss?"),
    ("walls", "Combien de murs y a-t-il sur cet étage ?"),
    ("rooms (spaces)", "How many rooms are on this level?"),
    ("doors", "Mitu ust on sellel korrusel?"),
]


def typed_gen():
    from bp.swiss.parse import parse_floor
    from bp.data import data_root

    qs = load_questions()
    test = [q for q in qs if q["split"] == "test"]
    gold = {(q["path"], q["question"]): q["answer"] for q in qs}
    out = []
    # Swiss: plans whose labels of the kind all have a dataset count question (so the gold is the dataset's)
    sw = sorted({q["path"] for q in test if q["source"] == "swiss_dwellings" and q["ext"] == "pdf"}, key=h)
    for kind, (labels, questions) in TYPED_KINDS.items():
        got = 0
        for p in sw:
            fl = parse_floor(str(data_root() / Path(p).with_suffix(".dxf")), None)
            on = {r.name for r in fl.rooms if r.number and r.name in labels}
            if not on:
                continue
            g = [gold.get((p, f"How many rooms labelled '{lab}' are there on this floor?")) for lab in sorted(on)]
            if any(x is None for x in g):
                continue
            out.append({"path": p, "source": "swiss_dwellings", "ext": "pdf", "split": "test",
                        "question": questions[got % len(questions)], "gold": sum(g), "kind": f"swiss {kind}",
                        "gold_from": " + ".join(f"'{lab}'" for lab in sorted(on))})
            got += 1
            if got == len(questions):
                break
    # IFC plan sheets: "this floor" = the sheet's storey (title of its SVG twin)
    from bp.crosscheck import svg_sheet

    sheets = sorted({q["path"] for q in test if q["source"] == "ifc_models" and "_plan-" in q["path"]}, key=h)
    tmpl = {}
    for q in qs:
        m = re.fullmatch(r"How many (.+) are shown on the floor plan of '(.+)'\?", q["question"])
        if m and q["source"] == "ifc_models":
            tmpl[(q["path"].split("_plan-")[0].rsplit(".", 1)[0], m.group(1), m.group(2))] = q["answer"]
    used = set()
    for p in sheets:  # up to two typed questions per sheet, each typed question once
        st = svg_sheet(str(data_root() / Path(p).with_suffix(".svg")))["storey"]
        model = p.split("_plan-")[0]
        n = 0
        for j, (what, question) in enumerate(TYPED_IFC):
            g = tmpl.get((model, what, st))
            if j in used or g is None or n == 2:
                continue
            out.append({"path": p, "source": "ifc_models", "ext": "pdf", "split": "test", "question": question,
                        "gold": g, "kind": "ifc sheet 'this floor'", "gold_from": f"{what} on '{st}'"})
            used.add(j)
            n += 1
        if len(used) == len(TYPED_IFC):
            break
    # the .ifc itself: "this floor" names no storey -> must abstain and ask which
    models = sorted({q["path"] for q in test if q["source"] == "ifc_models" and q["ext"] == "ifc"}, key=h)
    for p, question in zip(models, ["How many doors are on this floor?", "How many windows on this level?",
                                    "Wie viele Wände hat dieses Geschoss?"]):
        out.append({"path": p, "source": "ifc_models", "ext": "ifc", "split": "test", "question": question,
                    "gold": None, "kind": "ifc model 'this floor' (must ask which storey)", "gold_from": "-"})
    with open(TYPED, "w") as f:
        for it in out:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(f"{len(out)} -> {TYPED}")


def typed_run(tag="after"):
    from bp.router import Router, guess_type

    router = Router()
    items = [json.loads(l) for l in open(TYPED)]
    with open(typed_file(tag), "w") as f:
        for it in items:
            q = dict(it, type=guess_type(it["question"]), id=-1, answer=None)
            runs = [_solve(router, q) for _ in range(3)]  # asked three times: the answer must not move
            r = runs[0]
            stable = len({json.dumps(x["pred"], default=str) for x in runs}) == 1
            if it["gold"] is None:
                verdict = "abstained (right)" if r["pred"] is None else "answered (wrong)"
            elif r["pred"] is None:
                verdict = "abstained"
            else:
                verdict = "right" if is_correct("count", r["pred"], it["gold"]) else "wrong"
            f.write(json.dumps({**it, "type": q["type"], **r, "stable": stable, "verdict": verdict},
                               ensure_ascii=False, default=str) + "\n")
            print(verdict, "|", it["kind"], "|", it["question"][:60], "|", r["pred"], "gold", it["gold"],
                  file=sys.stderr)
    print(f"-> {typed_file(tag)}")


def _typed_section():
    B, A = _load(typed_file("before")), _load(typed_file("after"))
    if not A:
        return []
    L = ["## 4. Typed scope: room words and \"this floor\"", "",
         f"{len(A)} questions of the kind the usability test (app/USABILITY.md) found judges typing: everyday room "
         "words on Swiss plans that print their labels in German/French/Italian (\"How many bathrooms?\" on a plan "
         "that says 'Bad'), \"this floor\" on an IFC plan sheet (= that sheet's storey), and \"this floor\" on the "
         ".ifc model itself (no storey: the right answer is to ask which one). Gold = the dataset's answer to the "
         "matching template question on the same drawing. Each question is asked three times (router only; the "
         "app's vision fallback is not part of this run). Set: `runs/robustness_typed_scope.jsonl`.", "",
         "| kind | n | right before | right after | abstained before → after | wrong before → after | "
         "stable over 3 asks (after) |", "|---|---|---|---|---|---|---|"]

    def ok(v):
        return v in ("right", "abstained (right)")
    g = collections.defaultdict(list)
    for a in A:
        g[a["kind"]].append(a)
    gb = collections.defaultdict(list)
    for b in B or []:
        gb[b["kind"]].append(b)
    for k in list(g) + ["ALL"]:
        a = A if k == "ALL" else g[k]
        b = (B or []) if k == "ALL" else gb.get(k, [])
        L.append(f"| {'**ALL**' if k == 'ALL' else k} | {len(a)} | {sum(ok(x['verdict']) for x in b) if B else '-'} | "
                 f"**{sum(ok(x['verdict']) for x in a)}** | "
                 f"{sum(x['verdict'] == 'abstained' for x in b) if B else '-'} → "
                 f"{sum(x['verdict'] == 'abstained' for x in a)} | "
                 f"{sum(x['verdict'] in ('wrong', 'answered (wrong)') for x in b) if B else '-'} → "
                 f"{sum(x['verdict'] in ('wrong', 'answered (wrong)') for x in a)} | "
                 f"{sum(x['stable'] for x in a)}/{len(a)} |")
    cb, ca = (sum(x["cost_usd"] for x in v) for v in (B or [], A))
    L += ["", f"Paid calls: before ${cb:.4f} (the Haiku normaliser, once per question, then cached: before this fix "
          f"it was what mapped 'bathrooms' to 'Bad', and when it declined, the app handed the question to the "
          f"uncached vision reader, which gave 0, 3 and 4 on three asks in the usability test); after ${ca:.4f} "
          "(room words map to the plan's labels by a fixed table, `bp/swiss/rooms.py`; \"this floor\" on a sheet "
          "resolves to the storey in the sheet's title, `bp/solvers/ifc.py`; the app no longer sends Swiss or IFC "
          "drawings to the vision reader, and caches its answers to other typed questions per drawing).", ""]
    L += ["", "| question | drawing | gold | before | after | read as / explanation (after) |",
          "|---|---|---|---|---|---|"]
    bq = {(b["path"], b["question"]): b for b in B or []}
    for a in A:
        b = bq.get((a["path"], a["question"]))
        L.append(f"| {a['question']} | {Path(a['path']).name[:48]} | {a['gold']} ({a['gold_from']}) | "
                 f"{(str(b['pred'])[:30] + ' ' + b['verdict']) if b else '-'} | {a['pred']} {a['verdict']} | "
                 f"{str(a.get('explanation'))[:150]} |".replace("\n", " "))
    L.append("")
    return L


# ------------------------------------------------------------------ report
FINDINGS = """## Summary

- **Typed questions are now read, not just templates.** Paraphrase accuracy on the first set (149 Haiku
  paraphrases): **57.7 % → 84.6 %** (originals 86.6 %); 3 paraphrases are wrong where their original was right
  (re-run Sat 12:10 after the typed-question normaliser changes in section 5; before them 85.9 %, 0). On a **held-out set** of 122 casual, chat-style paraphrases written after the
  code: **49.2 % → 80.3 %** (originals 82.8 %; 81.1 % before the section 5 changes, within Haiku's run-to-run noise). That set's first run (77.9 %) exposed two more gaps, both fixed
  before the final run: unquoted IFC room/storey names fell back to a model-wide total at 0.95 (3 confident
  wrong answers), and unquoted Swiss labels did not reach the normaliser.
- **Must-abstain: 44/50 → 49/50** (50/50 before section 5: "How many elevators?" on a Swiss plan now reads as rooms labelled 'Ascenseur' and answers 2, showing that reading). Unknown IFC storeys ('Level 99', 'Basement -7', '17. Obergeschoss') now
  abstain with the list of real storeys instead of answering for the whole model. The normaliser sees 23 of
  these questions (the ones no parser understands) and declines all of them (NONE), so it never turns a
  nonsense question into an answer.
- **Dataset questions do not change.** All 127,043 dataset questions parse as before except 3 (quote fix,
  below), none reaches the normaliser, and the full test run `runs/router_full_test_v8.summary.md` scores
  **90.7 %** (v7: 90.0 %, v6: 89.5 %, v4: 88.2 %; since v4 CubiCasa went 82.2 % → 84.2 % (new detector) →
  85.1 % (flip test-time augmentation) → 86.1 % (VLM arbiter); Swiss 100.0 %, ifc_models 100.0 %, ifc_bench
  38.2 %). Language twins: 12,582 of 12,654 pairs agree (99.4 %; v7: all of them). The 72 that differ are
  CubiCasa pairs where the VLM arbiter overrode the detector in one language only: the fine-tuned VLM's
  precomputed answers were made per question text, so the en and fi twin can get different VLM readings.
  The parsers themselves still read both languages identically.
- **Cost:** the normaliser runs only on questions no parser understands: one Haiku call (~$0.0003-0.003, cached
  per question and drawing). Dataset questions stay $0.
"""

FIXES = """## What changed (bp/, this commit)

1. **Quotes are paired and word-boundary aware** (`bp/templates.py`, Swiss `_quoted`). An apostrophe opens a
   quote only when it is not glued to a word on its left ("What's", "Don't", "d'appartements" open nothing) and
   closes one only when not glued to a word on its right ('Cage d'escalier', 'IMMUNIZ'N ROOM (1D40)' stay whole).
   On all 127,043 dataset questions the parse changes for 3 (2 opening_design feet-inch strings, 1 IFC room whose
   name has an apostrophe, which a special case already rescued); every other parse is identical.
2. **IFC: unknown storey → abstain** (`bp/solvers/ifc.py`). A quoted name that is neither a storey nor introduced
   as the model's name ("the model 'X'", "the 'X' model", Modell/modelo/mudelis ...) gives "no storey named 'X'
   in this model; storeys are: ...", instead of a model-wide answer. Fuzzy storey matching (`bp/ifc/model.py`)
   now needs similarity ≥ 0.88 and identical signed numbers, so 'Basement -7' ≠ 'Basement' and 'Level 99' ≠
   'Level 9' (no dataset question uses the fuzzy path: every dataset storey slot matches exactly). Unquoted storey
   names in typed questions ("doors on Erdgeschoss") are found as whole phrases; a storey word with no
   findable name ("on the ground floor"), or a room named without quotes, abstains and goes to the normaliser
   with the storey and room lists (before, "area of WC 414B-23-003-006 on 3. Level" summed every room in the
   model at confidence 0.95).
3. **Swiss: a room label not on the plan is not 0 m²** (`bp/solvers/swiss.py`). An area summed over no rooms
   returns None ("no room labelled 'X' on this plan; labels are: ..."). A count stays 0 only for one of the 34
   room names the dev split asks about (`bp/swiss/room_labels.json`: 'Küche', 'Balcon', ...), where "none on
   this floor" is an honest answer; any other label abstains. Dev never asks for an absent label (0 of 11,542
   label questions has gold 0), so the rule costs nothing there.
4. **2D evidence for cut elements** (`bp/ifc/plan2d.py`). IfcConvert writes cut walls/doors/windows as
   `class="cut IfcWall"`; the SVG regex now accepts a class list. Warmond '2. Level' walls (q 89016): 0 → 84
   boxes; Entrance windows (q 88874): 0 → 22 boxes.
5. **Wider deterministic vocabulary** for common wordings: CubiCasa "storeys", "WC bowls / toilet seats",
   "door openings", "WC rooms / toilet rooms"; Swiss "marked / tagged / called / named" and a room number
   without the "(label)" bracket. Checked to leave every dataset question's parse unchanged.
6. **Question normaliser** (`bp/normalize.py`, hook in `bp/router.py`, `BP_NORMALIZE=1` default). Only when
   the routed solver cannot parse the question and abstains, one Claude Haiku call rewrites it into one
   supported template (real dev-split questions with placeholders) using only the names the drawing has
   (Swiss labels / room numbers / apartment letters; IFC storeys and rooms), or says NONE. Rewrites quoting a
   name that is not on the drawing are rejected. The solver re-runs on the rewrite; the result carries
   `normalized_question` and the explanation starts with "read as: ...". Cached per (question, drawing).

The fixes in 1-5 were written while looking at the first paraphrase set's failures (section 2a), so that set
measures the fixes on the cases they were made for. Section 2b is a **second, held-out paraphrase set**
(other originals, a casual "typed into a chat box" prompt), generated after the code was written; only its first
run's two gaps (see 2b) were fixed afterwards.
"""


def pct(a, b):
    return f"{a / b:.1%}" if b else "-"


def _load(p):
    return [json.loads(l) for l in open(p)] if Path(p).exists() else None


def _para_table(B, A):
    """before/after paraphrase accuracy per source/type (originals answered by the 'after' code)."""
    L = ["| source / type | n | original (after) | paraphrase before | paraphrase after | abstained before → after "
         "| answered wrong before → after |", "|---|---|---|---|---|---|---|"]
    gb, ga = collections.defaultdict(list), collections.defaultdict(list)
    for p in B:
        gb[f"{p['source']} / {p['type']}"].append(p)
    for p in A:
        ga[f"{p['source']} / {p['type']}"].append(p)
    for k in sorted(ga, key=lambda k: -len(ga[k])) + ["ALL"]:
        a = A if k == "ALL" else ga[k]
        b = B if k == "ALL" else gb.get(k, [])
        n = len(a)

        def wrong(v):
            return sum(p["para"]["pred"] is not None and not p["correct_para"] for p in v)
        L.append(f"| {'**ALL**' if k == 'ALL' else k} | {n} | {pct(sum(bool(p['correct_orig']) for p in a), n)} | "
                 f"{pct(sum(bool(p['correct_para']) for p in b), len(b))} | "
                 f"**{pct(sum(bool(p['correct_para']) for p in a), n)}** | "
                 f"{pct(sum(p['para']['pred'] is None for p in b), len(b))} → "
                 f"{pct(sum(p['para']['pred'] is None for p in a), n)} | "
                 f"{pct(wrong(b), len(b))} → {pct(wrong(a), n)} |")
    return L


def _para_detail(A):
    L = []
    lost = [p for p in A if p["correct_orig"] and not p["correct_para"]]
    won = [p for p in A if p["correct_para"] and not p["correct_orig"]]
    L += [f"After: right on the original but wrong on the paraphrase: {len(lost)}; the reverse: {len(won)}.", ""]
    if lost:
        L += ["| source | paraphrase | gold | answer (conf) | explanation |", "|---|---|---|---|---|"]
        for p in lost:
            L.append(f"| {p['source']} | {p['paraphrase'][:120]} | {str(p['gold'])[:25]} | "
                     f"{str(p['para']['pred'])[:30]} ({p['para'].get('confidence')}) | "
                     f"{str(p['para'].get('explanation'))[:110]} |".replace("\n", " "))
        L.append("")
    nz = [p for p in A if p["para"].get("normalize")]
    if nz:
        ok = sum(bool(p["correct_para"]) for p in nz if p["para"].get("normalized_question"))
        nrw = sum(1 for p in nz if p["para"].get("normalized_question"))
        cost = sum((p["para"]["normalize"] or {}).get("cost_usd", 0.0) for p in nz)
        L += [f"Normaliser: called on {len(nz)} of {len(A)} paraphrases (the others parsed directly); rewrote "
              f"{nrw} ({ok} then correct), declined {len(nz) - nrw}; Haiku cost in this run ${cost:.4f} (calls served from "
              "the cache cost $0; total normaliser spend is at the end).", "",
              "| paraphrase | read as | correct |", "|---|---|---|"]
        for p in nz:
            L.append(f"| {p['paraphrase'][:110]} | {(p['para'].get('normalized_question') or 'NONE: ' + str((p['para']['normalize'] or {}).get('why')))[:110]} | "
                     f"{'yes' if p['correct_para'] else 'no'} |".replace("\n", " "))
        L.append("")
    return L


def _verdict_table(A):
    L = ["| source | n | abstained | said not available | answered anyway |", "|---|---|---|---|---|"]
    g = collections.defaultdict(list)
    for a in A:
        g[a["source"]].append(a)
    for k in sorted(g) + ["ALL"]:
        v = A if k == "ALL" else g[k]
        n = len(v)
        c = collections.Counter(a["verdict"] for a in v)
        L.append(f"| {'**ALL**' if k == 'ALL' else k} | {n} | {pct(c['abstained (answer=None)'], n)} | "
                 f"{pct(c['said not available'], n)} | {pct(c['answered'], n)} |")
    return L


def report():
    L = ["# Robustness: language twins, paraphrases, must-abstain", "",
         "Generated by `analysis/robustness.py report`; TEST split only. Run logs: `runs/robustness_*.jsonl`. "
         "\"Before\" = the code before the parser fixes and the question normaliser, with the same detector.", "",
         FINDINGS, FIXES]
    # twins
    T = [json.loads(l) for l in open(TWINS)]
    L += ["## 1. Language twins", "",
          f"Every non-English test question has an English twin on the same drawing with the same gold answer "
          f"(router run `{RUN.name}`). Agreement = the router gives the same answer to both (numbers within 0.5 %; "
          "text answers compared verbatim, which is strict for LLM-written text).", "",
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
    L += ["## 2. English paraphrases (Claude Haiku)", "",
          "Each English test question is rewritten once by Claude Haiku; the router answers the original and the "
          "paraphrase with the same code. Text answers (ifc_bench) are scored by the LLM judge (bp/judge.py), "
          "numbers by the official tolerance. \"Answered wrong\" includes low-confidence answers.", ""]
    for which, title, blurb in (
            ("orig", "2a. First set (149, used to find the bugs)",
             "Stratified over source, type and template; prompt `PARA_SYSTEM`: same meaning, quoted names copied "
             "exactly. (The earlier version of this page measured 86.6 % → 58.4 % on it with the previous CubiCasa "
             "detector; \"before\" here is the same old parser code with the current detector.) Every paraphrase "
             "here is now handled by the deterministic parsers; the normaliser is not needed."),
            ("fresh", "2b. Held-out set (casual typing, generated after the fixes)",
             "Other originals (salted pick, same quotas); prompt `PARA_SYSTEM_FRESH`: what a person would type "
             "into a chat box, quote marks optional. Its first run with the new code scored 77.9 % "
             "(`runs/robustness_para_fresh_after1.jsonl`) and exposed two gaps (unquoted IFC room/storey names, "
             "unquoted Swiss labels), which were fixed before the final run below; nothing else was changed for "
             "it.")):
        B, A = _load(para_run_file(which, "before")), _load(para_run_file(which, "after"))
        if not (A and B):
            continue
        L += [f"### {title}", "", blurb, ""] + _para_table(B, A) + [""] + _para_detail(A)
    # abstain
    Ab, Aa = _load(abst_file("before")), _load(abst_file("after"))
    if Aa:
        L += ["## 3. Must-abstain questions", "",
              f"{len(Aa)} hand-written questions on test-split drawings whose honest answer is \"not on this drawing\": "
              "objects that are not drawn or not in our vocabulary (elevators on a Finnish single-family plan), storeys "
              "and rooms that do not exist (an IFC storey 'Level 99', Swiss room 9.99, apartment Z), information no "
              "drawing carries (rent, build year, WiFi password) and nonsense (unicorns). Correct behaviour: "
              "answer = None (abstain) or a text answer saying it is not available. These questions do reach the "
              "normaliser when they do not parse; it must answer NONE.", ""]
        if Ab:
            okb = sum(a["verdict"] != "answered" for a in Ab)
            L += ["Before:", ""] + _verdict_table(Ab) + ["", f"Correct behaviour before: {okb}/{len(Ab)}.", ""]
        ok = sum(a["verdict"] != "answered" for a in Aa)
        L += ["After:", ""] + _verdict_table(Aa) + ["", f"**Correct behaviour after: {ok}/{len(Aa)} "
                                                     f"({pct(ok, len(Aa))}).**", "",
              "Every must-abstain question and what the router did (after):", "",
              "| source | kind | question | verdict | answer / explanation |", "|---|---|---|---|---|"]
        for a in Aa:
            ans = a["pred"] if a["pred"] is not None else a.get("explanation")
            L.append(f"| {a['source']} | {a['kind']} | {a['question'][:90]} | {a['verdict']} | "
                     f"{str(ans)[:120]} |".replace("\n", " "))
        L.append("")
    L += _typed_section()
    spend = collections.Counter()
    for r in map(json.loads, open(ROOT / "cache/llm_spend.jsonl")):
        spend[r["tag"]] += r["cost_usd"]
    L += [f"Paid usage (all runs of this analysis, from cache/llm_spend.jsonl): paraphrase generation "
          f"${spend['robustness-paraphrase'] + spend['robustness-paraphrase-fresh']:.3f}, normaliser "
          f"${spend['normalize']:.3f}.", ""]
    # section 5 is written by hand from analysis/typed_eval.py runs; keep it when regenerating
    mark, old = "<!-- section 5: analysis/typed_eval.py -->", DOC.read_text() if DOC.exists() else ""
    DOC.write_text("\n".join(L) + ("\n" + old[old.index(mark):] if mark in old else ""))
    print(f"-> {DOC}")


if __name__ == "__main__":
    {"twins": twins, "para-gen": para_gen, "para-gen-fresh": lambda: para_gen(fresh=True), "para-run": para_run,
     "abstain-run": abstain_run, "typed-gen": typed_gen, "typed-run": typed_run, "report": report}[sys.argv[1]](*sys.argv[2:])
