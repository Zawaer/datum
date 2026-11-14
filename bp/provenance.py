"""Provenance checker for LLM-written answers: every number and every quoted name must be traceable.

    check(answer_text, cited_sources, computed=()) -> {"status", "numbers", "quotes", "note", ...}

`cited_sources` are the source lines the model cited (fact-sheet lines, drawing text segments). Each is a
string, optionally prefixed with its id ("[f12] IfcDoor: 14 ..."), or an (id, text) pair. Without an id a
source is called "s0", "s1", ...

A number in the answer is *traced* when
  - it appears in a cited source line (same value, tolerating rounding to the precision the answer shows;
    1 234,5 / 1,234.5 / 1.234,5 / 12 % / 3.5 m2 / 200mm all normalised), or
  - it is derived from traced values: the sum of a column of the answer's own list (a "total" line), the sum
    of a column of the cited lines, the number of list lines / cited lines (a count), or a sum, difference,
    product, ratio or percentage of two traced values (`computed` adds values the caller recomputed, e.g. a
    total re-added from the cited items).
A number that only appears in `context` (lines that were shown to the model but not cited) is *uncited*.
Numbers in a "rough estimate" tail are marked "estimate" and not held against the answer (the answer says
it is an estimate). Quoted names ('...', "...", ‘...’, “...”) must appear as substrings of a cited line
(case- and whitespace-insensitive); identifiers with digits glued to letters (A-801, IFC2X3) likewise.

status: "verified"   every number and quote is traced to a cited line or derived from traced values;
        "partial"    >= 80 % of them are (the rest uncited or untraceable), or there is nothing to check
                     (claims == 0);
        "unverified" < 80 % are traced to the cited lines. The 80 % cut was chosen on the ifc_bench dev
                     split: answers below it were judge-correct 30 % of the time (vs 52 % above), so
                     solvers cap their confidence at 0.3 (docs/PROVENANCE.md).
"""
from __future__ import annotations

import itertools
import math
import re

UNITS = r"(?:mm|cm|m|m2|m²|m3|m³|km|sq\s?m|sqm|sf|sq\s?ft|ft|in|kg|t|kn|mpa|kpa|pa|kw|w|l|°|deg|%|x)"
# a number: grouped thousands (space, nbsp, thin space, comma, dot) or plain, optional decimal part
NUM_RX = re.compile(
    r"(?<![\d.,/])(?P<sign>(?<![\w])[-−])?(?P<num>\d{1,3}(?:(?:[   ](?=\d{3}(?!\d)))\d{3}|[,.]\d{3}(?![\d]))+(?:[.,]\d+)?"
    r"|\d+(?:[.,]\d+)?)(?P<frac>/\d+)?(?P<after>[A-Za-z²³°%]*)")
# quotes; a quote mark right after a digit is a foot / inch mark (12' - 0"), after a letter an apostrophe
QUOTE_RX = re.compile(r"(?<![\w])'(?=\S)([^'\n]{2,80}?)(?<=\S)'(?!\w)|(?<![\w])\"(?=\S)([^\"\n]{2,80}?)(?<=\S)\"(?!\w)"
                      r"|‘([^’\n]{2,80})’|“([^”\n]{2,80})”")
EST_RX = re.compile(r"(?i)rough estimate|\bestimate\s*:")
LIST_MARK_RX = re.compile(r"^\s*(\d{1,2})[.)]\s")
UNVERIFIED_BELOW = 0.8  # share of claims traced to the cited sources
UNIT_SCALE = {"mm": 1e-3, "cm": 1e-2, "m": 1.0, "km": 1e3}


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", str(s)).lower()


def _interpretations(tok: str) -> list[tuple[float, int]]:
    """Possible (value, decimals) readings of a numeric token like '1 234,5', '1,234', '1.234', '12,5'."""
    t = tok.replace(" ", " ").replace(" ", " ")
    if " " in t:
        t = t.replace(" ", "")
    out = []
    has_c, has_d = "," in t, "." in t
    if has_c and has_d:  # the last separator is the decimal mark
        dec = "," if t.rfind(",") > t.rfind(".") else "."
        grp = "." if dec == "," else ","
        s = t.replace(grp, "").replace(dec, ".")
        out.append((float(s), len(s.split(".")[1])))
    elif has_c or has_d:
        sep = "," if has_c else "."
        parts = t.split(sep)
        if len(parts) > 2:  # 1,234,567 / 1.234.567
            out.append((float("".join(parts)), 0))
        else:
            if len(parts[1]) == 3 and parts[0] != "0":  # 1,234 or 1.234: thousands first, decimal second
                out.append((float(parts[0] + parts[1]), 0))
            out.append((float(parts[0] + "." + parts[1]), len(parts[1])))
    else:
        out.append((float(t), 0))
    return out


def extract_numbers(text: str, skip_list_marks: bool = True) -> list[dict]:
    """Numbers in a text: {"raw", "vals": [(value, decimals)], "unit", "embedded", "line", "pos", "word"}."""
    out = []
    for li, line in enumerate(str(text).splitlines()):
        lm = LIST_MARK_RX.match(line) if skip_list_marks else None
        for m in NUM_RX.finditer(line):
            if lm and m.start("num") == lm.start(1):
                continue  # "1. " list numbering
            if re.fullmatch(r"(?i)[a-z]{1,2}[23²³]", line[max(0, m.start() - 2):m.end()].strip()) and \
                    re.match(r"(?i)(mm|cm|m|sq|ft|in|yd)$", line[max(0, m.start() - 2):m.start()].strip()):
                continue  # the 2 of "m2"
            num, after = m.group("num"), m.group("after")
            before = line[max(0, m.start() - 1):m.start()]
            unit = after.lower() if re.fullmatch(UNITS, after.lower() or "-") else ""
            before2 = line[max(0, m.start() - 2):m.start()]
            embedded = bool(re.match(r"[A-Za-z_]", before)) or (bool(after) and not unit) or \
                bool(re.fullmatch(r"[A-Za-z0-9]-", before2))  # A-801, W-12
            word = re.search(r"\S*$", line[:m.start()]).group(0) + line[m.start():m.end()] + \
                re.match(r"\S*", line[m.end():]).group(0)
            if not unit and not embedded:  # unit after a space ("3.5 m2", "12 %")
                um = re.match(r"\s?(" + UNITS + r")(?![A-Za-z0-9²³])", line[m.end():], re.I)
                if um:
                    unit = um.group(1).lower()
            sign = -1.0 if m.group("sign") else 1.0
            vals = [(sign * v, d) for v, d in _interpretations(num)]
            if m.group("frac"):
                den = float(m.group("frac")[1:])
                if den:
                    vals = [(v / den, 3) for v, _ in vals] + vals
            out.append({"raw": m.group(0), "vals": vals, "unit": unit, "embedded": embedded, "line": li,
                        "pos": m.start(), "word": word.strip(".,;:()[]{}'\"")})
    return out


def _close(a: float, da: int, b: float) -> bool:
    """Is source value b shown as a (rounded to da decimals)?"""
    tol = 0.5 * 10 ** (-da) + 1e-9 * max(1.0, abs(a))
    return abs(a - b) <= tol


def _parse_sources(sources) -> list[tuple[str, str]]:
    out = []
    for i, s in enumerate(sources or []):
        if isinstance(s, (tuple, list)) and len(s) == 2:
            out.append((str(s[0]), str(s[1])))
            continue
        s = str(s)
        m = re.match(r"\s*\[([\w.:-]+)\]\s*", s)
        out.append((m.group(1), s[m.end():]) if m else (f"s{i}", s))
    return out


def _source_values(srcs):
    """{sid: [(value, decimals, unit)]} and per-source numeric columns."""
    vals = {}
    for sid, text in srcs:
        vs = []
        for n in extract_numbers(text, skip_list_marks=False):
            if n["embedded"]:
                continue
            for v, d in n["vals"]:
                vs.append((v, d, n["unit"]))
        vals[sid] = vs
    return vals


def _find_in(values: dict, cands, unit: str):
    for sid, vs in values.items():
        for v, _d, u in vs:
            conv = [v]
            if unit in UNIT_SCALE and u in UNIT_SCALE and u != unit:  # 200 mm vs 0.2 m
                conv.append(v * UNIT_SCALE[u] / UNIT_SCALE[unit])
            for a, da in cands:
                if any(_close(a, da, x) for x in conv):
                    return sid, a
    return None, None


def _group_pool(lines, srcs, svals):
    """Per answer line "- Offices (Buero): 17 spaces, 289.35 m2": the cited lines that mention a word of the
    label ("Buero"), their count and the sums of their numeric columns (a breakdown by group)."""
    pool = []
    low = {sid: t.lower() for sid, t in srcs}
    for ln in lines:
        m = re.match(r"\s*(?:[-*•]|\d{1,2}[.)])?\s*([^:\n]{2,80}):", ln)
        if not m:
            continue
        words = {w for w in re.findall(r"[^\W\d_]{3,}", m.group(1).lower())} - {"total", "and", "the", "with"}
        hit = [sid for sid in low if any(w in low[sid] for w in words)]
        if len(hit) < 2 or len(hit) == len(low):
            continue
        pool.append(("count", float(len(hit))))
        cols = [[v for v, _d, _u in svals[sid]] for sid in hit]
        for k in range(min(4, max(len(c) for c in cols))):
            pool.append(("sum", sum(c[k] for c in cols if len(c) > k)))
    return pool[:60]


def _derived_pool(nums, srcs_vals, computed, n_list_lines, n_sources):
    """Named values that may legitimately appear in an answer although no line states them."""
    pool = [("computed", float(c)) for c in computed if c is not None]
    traced = [n["value"] for n in nums if n.get("found_in") not in (None, "estimate")]
    # columns of the answer's own list (k-th number of each line), and all its numbers per line
    by_line = {}
    for n in nums:
        if n.get("found_in") not in (None, "estimate") and not n["embedded"]:
            by_line.setdefault(n["line"], []).append(n["value"])
    lines = list(by_line.values())
    if len(lines) >= 2:
        for k in range(max(len(x) for x in lines)):
            col = [x[k] for x in lines if len(x) > k]
            if len(col) >= 2:
                pool.append(("sum", sum(col)))
                pool.append(("sum", sum(col) / len(col)))  # average
        last = [x[-1] for x in lines]
        pool.append(("sum", sum(last)))
    # columns of the cited lines
    svs = [[v for v, _d, _u in vs] for vs in srcs_vals.values() if vs]
    if len(svs) >= 2:
        for k in range(min(4, max(len(x) for x in svs))):
            col = [x[k] for x in svs if len(x) > k]
            pool.append(("sum", sum(col)))
            pool.append(("sum", sum(col) / len(col)))
    for vs in svs:
        if len(vs) >= 2:
            pool.append(("sum", sum(vs)))
    pool += [("count", float(n_list_lines)), ("count", float(n_sources))]
    # pairwise arithmetic over traced values (+ computed + column sums), capped. Marked "pair": with ~40
    # values there are ~8000 results, so they may only explain numbers shown with decimals or as a percentage
    # (an area w x h, a share); a bare integer matched one by chance (a fabricated count is caught).
    base = list(dict.fromkeys(traced + [v for _, v in pool if _ == "sum" or _ == "computed"]))[:40]
    for a, b in itertools.permutations(base, 2):
        pool.append(("sum", a + b, "pair"))
        pool.append(("difference", a - b, "pair"))
        pool.append(("product", a * b, "pair"))
        if b:
            pool.append(("ratio", a / b, "pair"))
            pool.append(("ratio", 100 * a / b, "pair"))
    return pool


def check(answer_text, cited_sources, computed=(), context=()) -> dict:
    text = "" if answer_text is None else str(answer_text)
    srcs = _parse_sources(cited_sources)
    ctx = _parse_sources(context)
    fam = {re.sub(r"\d+$", "", sid) for sid, _ in srcs + ctx if re.fullmatch(r"[a-z]{1,4}\d+", sid)}
    for f in fam:  # inline citations ("[f24]", "f52–f58") are references, not claims
        text = re.sub(r"\[?\b" + re.escape(f) + r"\d+\b\]?", " ", text)
    src_norm = {sid: _norm(t) for sid, t in srcs}
    ctx_norm = {sid: _norm(t) for sid, t in ctx}
    svals, cvals = _source_values(srcs), _source_values(ctx)
    est = EST_RX.search(text)
    est_at = None
    if est:  # the estimate tail starts at the line holding the marker
        est_at = text[:est.start()].count("\n")
    lines = text.splitlines()
    n_list = sum(1 for ln in lines if re.match(r"\s*(?:[-*•]|\d{1,2}[.)])\s", ln))

    nums = []
    for n in extract_numbers(text):
        v0 = n["vals"][0][0]
        rec = {"value": v0, "raw": n["raw"], "line": n["line"], "embedded": n["embedded"], "found_in": None,
               "_n": n}
        if est_at is not None and n["line"] >= est_at:
            rec["found_in"] = "estimate"
        elif n["embedded"]:  # part of a name / code: the whole word must be in a source
            w = _norm(n["word"])
            rec["found_in"] = next((sid for sid, t in src_norm.items() if w and w in t), None)
            if rec["found_in"] is None:
                c = next((sid for sid, t in ctx_norm.items() if w and w in t), None)
                rec["found_in"] = f"uncited:{c}" if c else None
        else:
            sid, a = _find_in(svals, n["vals"], n["unit"])
            if sid is None:
                sid, a = _find_in(cvals, n["vals"], n["unit"])
                sid = f"uncited:{sid}" if sid is not None else None
            if sid is not None:
                rec["found_in"], rec["value"] = sid, a
        nums.append(rec)
    # second pass: derived values (totals, counts, percentages) from what is already traced
    if any(r["found_in"] is None or str(r["found_in"]).startswith("uncited:") for r in nums):
        pool = _group_pool(lines, srcs, svals) + _derived_pool(nums, svals, computed, n_list, len(srcs))
        for r in nums:
            if r["found_in"] is None or str(r["found_in"]).startswith("uncited:"):
                if r["embedded"]:
                    continue
                for kind, pv, *pair in pool:
                    hit = next((a for a, da in r["_n"]["vals"] if _close(a, da, pv)
                                and (not pair or da > 0 or r["_n"]["unit"] == "%")), None)
                    if hit is not None:
                        r["found_in"], r["value"] = kind, hit
                        break

    quotes = []
    for m in QUOTE_RX.finditer(text):
        q = next(g for g in m.groups() if g)
        if not re.search(r"[A-Za-z]", q):
            continue
        qn = _norm(q)
        sid = next((s for s, t in src_norm.items() if qn in t), None)
        if sid is None:
            c = next((s for s, t in ctx_norm.items() if qn in t), None)
            sid = f"uncited:{c}" if c else None
        line = text[:m.start()].count("\n")
        if est_at is not None and line >= est_at and sid is None:
            sid = "estimate"
        quotes.append({"text": q, "found_in": sid})

    claims = [r["found_in"] for r in nums] + [q["found_in"] for q in quotes]
    claims = [c for c in claims if c != "estimate"]
    cited = sum(1 for c in claims if c is not None and not str(c).startswith("uncited:"))
    traceable = sum(1 for c in claims if c is not None)
    if not claims:
        status, note = "partial", "no numbers or quoted names to check"
    elif cited == len(claims):
        status, note = "verified", f"all {len(claims)} numbers/names traced to the cited sources"
    elif cited >= UNVERIFIED_BELOW * len(claims):
        miss = len(claims) - cited
        status, note = "partial", f"{miss} of {len(claims)} numbers/names not in the cited sources" + \
            (f" ({traceable - cited} found in uncited lines)" if traceable > cited else "")
    else:
        status, note = "unverified", f"only {cited} of {len(claims)} numbers/names traced to the cited sources" + \
            (f" ({traceable - cited} more in uncited lines)" if traceable > cited else "")
    bad = [r["raw"] for r in nums if r["found_in"] is None] + [q["text"] for q in quotes if q["found_in"] is None]
    if bad and status != "verified":
        note += ": " + ", ".join(dict.fromkeys(bad[:6])) + (" ..." if len(bad) > 6 else "")
    for r in nums:
        r.pop("_n", None)
    return {"status": status, "claims": len(claims), "traced": cited, "numbers": nums, "quotes": quotes,
            "note": note}


def verified_sources(prov: dict) -> set:
    """Ids of the cited sources that at least one number or quote was found in."""
    out = set()
    for r in prov.get("numbers", []) + prov.get("quotes", []):
        f = r.get("found_in")
        if f and f not in ("sum", "difference", "product", "ratio", "count", "computed", "estimate") \
                and not str(f).startswith("uncited:"):
            out.add(f)
    return out


def apply(result: dict, prov: dict, cap: float = 0.3) -> dict:
    """Attach `prov` to a solver result: cap the confidence of unverified answers and say why."""
    result["provenance"] = prov
    if prov["status"] == "unverified":
        if result.get("confidence") is not None and result["confidence"] > cap:
            result["confidence"] = cap
        result["explanation"] = (str(result.get("explanation") or "") + f" | provenance: {prov['note']}").strip(" |")
    return result
