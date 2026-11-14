"""A question that names something the drawing does not have ("rooms labelled 'skibidi'", "doors on 'Level 99'").

The exact solvers answer it with a structured abstention instead of a vague "not understood":

    {"answer": None, "not_found": {"kind": "label"|"room"|"storey"|"apartment", "asked": "skibidi",
                                   "available": [names on this drawing, most frequent first, <= 12]}}

and one plain sentence ("No room on this plan is labelled 'skibidi'."). The router then asks the normaliser once
whether the asked name is a typo / abbreviation / translation / synonym of one of the drawing's own names
(bp/normalize.py `match_name`, the reply may only be one of those names) and re-asks with it; the UI offers the
available names as chips that re-ask the same question with that name (`options`, built here).
$0 and deterministic except that one cached Haiku call.
"""
from __future__ import annotations

import re
from collections import Counter

MAX_AVAILABLE = 12

_WHAT = {"label": "room label", "room": "room", "storey": "storey", "apartment": "apartment"}


def ranked(names) -> list[str]:
    """Distinct non-empty names, most frequent first (ties in drawing order: storeys stay bottom to top)."""
    c = Counter(n for n in names if n)
    return sorted(c, key=lambda n: -c[n])  # (Counter keeps first-seen order; sorted is stable)


def sentence(kind: str, asked: str, where: str = "on this plan") -> str:
    if kind == "label":
        return f"No room {where} is labelled '{asked}'."
    if kind == "room":
        named = asked if re.fullmatch(r"[A-Z]?\d+(?:\.\d+)*", asked) else f"named '{asked}'"
        return f"There is no room {named} {where}."
    if kind == "storey":
        return f"There is no storey named '{asked}' {where}."
    if kind == "apartment":
        return f"There is no apartment {asked} {where}."
    return f"'{asked}' is not on this drawing."


def abstain(base: dict, kind: str, asked: str, names, where: str = "on this plan", detail: str = "") -> dict:
    """The structured abstention. `names`: every name of this kind on the drawing (repeats count for the order)."""
    allnames = ranked(names)
    expl = sentence(kind, asked, where)
    if allnames:
        expl += f" {_WHAT[kind].capitalize()}s here: " + ", ".join(
            f"'{n}'" for n in allnames[:MAX_AVAILABLE]) + (" ..." if len(allnames) > MAX_AVAILABLE else "") + "."
    if detail:
        expl += " " + detail
    return {**base, "answer": None, "confidence": 0.0, "explanation": expl,
            "not_found": {"kind": kind, "asked": asked, "available": allnames[:MAX_AVAILABLE]},
            "_not_found_all": allnames}


def substitute(question: str, asked: str, name: str, kind: str | None = None) -> str | None:
    """The same question with the asked name replaced by `name` (first occurrence; quoted forms first), or None."""
    if not asked:
        return None
    if kind == "apartment":
        m = re.search(rf"(?i:apartment|wohnung|appartement|appartamento|logement|unit|flat)\s+({re.escape(asked)})\b",
                      question)
        if m:
            return question[:m.start(1)] + name + question[m.end(1):]
    for qa, qb in (("'", "'"), ('"', '"'), ("«", "»"), ("“", "”"), ("„", "“"), ("‘", "’")):
        i = question.find(qa + asked + qb)
        if i >= 0:
            return question[:i + len(qa)] + name + question[i + len(qa) + len(asked):]
    m = re.search(rf"(?<!\w){re.escape(asked)}(?!\w)", question)
    if m is None:
        m = re.search(re.escape(asked), question, re.I)
    if m is None:
        return None
    return question[:m.start()] + name + question[m.end():]


def options(question: str, nf: dict, n: int = 8) -> list[dict]:
    """Chips for the UI: [{"name", "question"}] for the first `n` available names."""
    out = []
    for name in nf.get("available") or []:
        q2 = substitute(question, nf.get("asked") or "", name, nf.get("kind"))
        if q2 and q2 != question:
            out.append({"name": name, "question": q2})
        if len(out) >= n:
            break
    return out
