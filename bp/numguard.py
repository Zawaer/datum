"""Number safety: a thousands separator read as a decimal point.

A model answering a German question writes "4.470" for 4,470 SF, which parses as 4.47; a label "1,050 SF" read
with a decimal comma becomes 1.05. The answer's own evidence carries the printed numbers, so a numeric answer that
is exactly 1/1000 of a printed number (or of the sum of the evidence's printed numbers) is the printed number, and
one that is about 1/1000 of one is rejected (abstains; the guess stays visible as tentative_answer). An answer that
is itself printed in the evidence ("2.500 m" read as 2.5) is never touched, and plain metric dimensions (6200,
a millimetre string) do not count: only numbers printed with a digit-group separator or with an area / length unit
(SF, LF, m², sq ft).
"""
from __future__ import annotations

import re

_GROUPED = re.compile(r"(?<![\d.,])-?\d{1,3}(?:[,.  ]\d{3})+(?![\d])(?![.,]\d)")
_PLAIN = re.compile(r"(?<![\d.,])-?\d+(?:[.,]\d+)?(?![\d])")
_IMPERIAL = re.compile(r"^\s*(?:SF|S\.F\.|sq\.? ?ft|ft²|ft2|LF|square f)", re.I)
_UNIT_AFTER = re.compile(r"^\s*(?:SF|S\.F\.|sq\.? ?ft|ft²|ft2|LF|m²|m2|sqm|square)", re.I)


def printed_numbers(text: str) -> list[tuple[float, bool, float | None]]:
    """[(value read as thousands-grouped / with a unit, counts for the 1000x check, value as plainly read)]."""
    s = str(text or "")
    out, spans = [], []
    for m in _GROUPED.finditer(s):
        g = m.group(0)
        v = float(re.sub(r"[,.  ]", "", g))
        # "2.500 m" may be a decimal (European style); "1,050" and "1.403 SF" (an imperial unit) are thousands
        plain = float(g) if re.fullmatch(r"-?\d{1,3}\.\d{3}", g) and not _IMPERIAL.match(s[m.end():]) else None
        out.append((v, True, plain))
        spans.append(m.span())
    for m in _PLAIN.finditer(s):
        if any(a <= m.start() < b for a, b in spans):
            continue
        v = float(m.group(0).replace(",", "."))
        out.append((v, bool(_UNIT_AFTER.match(s[m.end():])), v))
    return out


def answer_number(ans) -> float | None:
    if isinstance(ans, bool) or ans is None:
        return None
    if isinstance(ans, (int, float)):
        return float(ans)
    m = re.match(r"^\s*~?\s*(-?\d[\d,]*(?:\.\d+)?)\s*(?:SF|sq\.? ?ft|ft²|m²|m2|m|mm|LF|ft)?\.?\s*$", str(ans), re.I)
    if not m:
        return None
    t = m.group(1)
    if re.fullmatch(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?", t):
        t = t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _main_number(e: dict) -> float | None:
    """The number one evidence row stands for: its value, else the last thousands / unit number of its label."""
    v = e.get("value")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    nums = [n for n, counts, _ in printed_numbers(e.get("label") or e.get("text") or "") if counts]
    return nums[-1] if nums else None


def check(res: dict) -> dict:
    """Correct or reject a numeric answer that is 1/1000 of what its evidence prints (in place; returns res)."""
    if not isinstance(res, dict):
        return res
    v = answer_number(res.get("answer"))
    if v is None or v == 0 or abs(v) >= 1000:
        return res
    ev = [e for e in res.get("evidence") or [] if isinstance(e, dict)]
    plain_seen, cands = set(), []
    for e in ev:
        for txt in (e.get("label"), e.get("text")):
            for n, counts, plain in printed_numbers(txt or ""):
                if plain is not None:
                    plain_seen.add(round(plain, 6))
                if counts:
                    cands.append(n)
        val = e.get("value")
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            plain_seen.add(round(float(val), 6))
            if abs(val) >= 1000:
                cands.append(float(val))
    if round(v, 6) in plain_seen:
        return res  # the answer is printed as such in its own evidence
    mains = [_main_number(e) for e in ev]
    if len(ev) >= 2 and all(x is not None for x in mains):
        cands.append(sum(mains))
    cands = [c for c in cands if abs(c) >= 1000]
    target = 1000 * v
    exact = [c for c in cands if abs(c - target) <= 0.5]
    if exact:
        c = exact[0]
        res["answer_read"] = res.get("answer")
        res["answer"] = int(round(c)) if abs(c - round(c)) < 1e-9 else c
        res["number_guard"] = {"read": res["answer_read"], "printed": res["answer"], "action": "corrected"}
        res["explanation"] = (f"read as {res['answer_read']}, but the sheet prints {res['answer']:,}: a thousands "
                              "separator was taken for a decimal point, so the printed number is used | "
                              + (res.get("explanation") or ""))
        return res
    near = [c for c in cands if abs(c / target - 1) < 0.02]
    if near:
        res["tentative_answer"], res["answer"] = res.get("answer"), None
        res["number_guard"] = {"read": res["tentative_answer"], "printed": near[0], "action": "rejected"}
        res["explanation"] = (f"read {res['tentative_answer']}, about 1/1000 of the printed {near[0]:,.0f}: a "
                              "thousands separator may have been read as a decimal point, so no answer is given | "
                              + (res.get("explanation") or ""))
    return res
