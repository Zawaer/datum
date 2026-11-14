"""The English intent of an upload question, before it is routed.

* `to_english`: the sheet specialists (bp/sheets) match English keywords ("classroom", "baseboard", "slab ... D22").
  A question written in Finnish, German or Swedish is translated once (one Haiku call, cached in
  cache/intent.jsonl) into the English a drawing would use; numbers, units, tags and sheet ids must survive the
  translation unchanged or it is not used.
* `split_asks`: "How many check valves and what size is the discharge header?" is two asks. Each part is answered
  through the normal router and the answers are shown together (Router._parts). "... and how many of them are 3'-0"
  wide?" gets its subject back from the first part.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from pathlib import Path

from bp.typofix import is_foreign

CACHE = Path(os.environ.get("BP_CACHE", "cache")) / "intent.jsonl"
_lock = threading.Lock()
_mem: dict | None = None

TRANSLATE_SYSTEM = """You translate a user's question about a construction drawing (floor plan, slab / reinforcement
plan, piping plan, door schedule) into plain English, the way an English drawing would word it.
Rules:
- Reply with the English question only, one line, no quotes, no comment.
- Keep every number, unit, tag, bar size, sheet id and code exactly as written (300 mm, D22, CV-1, 2. OG -> 2nd floor
  is fine, A-101F, 3'-0").
- Keep words that are already English (often in brackets) as they are.
- Use drawing vocabulary: luokkahuone -> classroom, ryhmätila / grupprum -> group room, makuuhuone -> bedroom,
  jalkalista / Sockelleiste -> baseboard, laatta / Bodenplatte -> slab, raudoitus / Bewehrung -> reinforcement,
  pinta-ala / Fläche / yta -> area, Verkehrsfläche -> circulation area, Technikraum -> mechanical room,
  kanaali / rörkanal -> trench, paineiskusäiliö -> surge tank, polttoainepumppu -> fuel pump, moduuli -> module,
  kerros / Geschoss / plan (floor) -> floor, asuntolahuone -> dorm room, esteetön -> accessible (ABA).
- Keep the question's meaning; do not answer it."""


def _key(q: str) -> str:
    return hashlib.sha1(("v1\x00" + " ".join(q.split())).encode()).hexdigest()


def _cache_get(k):
    global _mem
    with _lock:
        if _mem is None:
            _mem = {}
            if CACHE.exists():
                for line in CACHE.read_text(encoding="utf-8").splitlines():
                    try:
                        r = json.loads(line)
                        _mem[r["k"]] = r
                    except (json.JSONDecodeError, KeyError):
                        pass
        return _mem.get(k)


def _cache_put(rec):
    with _lock:
        if _mem is not None:
            _mem[rec["k"]] = rec
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def needs_translation(question: str) -> bool:
    if is_foreign(question):
        return True
    # several words with letters English does not use (ä ö å ü ß)
    return len(re.findall(r"\b\w*[äöåüßÄÖÅÜ]\w*\b", question)) >= 2


def _numbers(s: str) -> list[str]:
    return re.findall(r"\d+", s)


def valid_translation(src: str, en: str) -> bool:
    """Every number of the question is still there (D22 stays D22, 300 mm stays 300 mm), and it is one line."""
    if not en or "\n" in en.strip() or len(en) > 3 * len(src) + 40:
        return False
    got = _numbers(en)
    return all(n in got for n in _numbers(src))


def to_english(question: str) -> dict:
    """-> {"question": English question or None (already English / failed), "cost_usd", "cached"}."""
    if not question or not needs_translation(question) or os.environ.get("BP_TRANSLATE", "1") != "1":
        return {"question": None, "cost_usd": 0.0}
    k = _key(question)
    hit = _cache_get(k)
    if hit is not None:
        return {"question": hit.get("en"), "cost_usd": 0.0, "cached": True}
    from bp.generic import llm

    r = llm.ask(f"Question: {question}\n\nEnglish:", model="haiku", system=TRANSLATE_SYSTEM, timeout=30,
                tag="translate", think=False)
    cost = float(r.get("cost_usd") or 0.0)
    if r.get("error"):
        return {"question": None, "cost_usd": cost, "why": str(r["error"])[:120]}
    en = (r.get("text") or "").strip().strip('`"\'“”').strip()
    en = re.sub(r"^(?:english|translation)\s*:\s*", "", en, flags=re.I).strip()
    en = en if valid_translation(question, en) else None
    _cache_put({"k": k, "question": question, "en": en, "raw": (r.get("text") or "")[:300], "cost_usd": cost})
    return {"question": en, "cost_usd": cost}


# ------------------------------------------------------------------ two asks in one question
_ASK = r"(?:how\s+(?:many|much|big|large|long|wide|high|tall|deep|thick)|what|which|where|is\s+there|are\s+there)"
_JOIN = re.compile(rf"\s*(?:,\s*and|\band|;|,)\s+(?={_ASK}\b)", re.I)
_SUBJ = re.compile(r"^how\s+many\s+(?P<noun>.+?)\s+(?P<verb>are|is|were|was|do|does|can|in|on|of)\b\s*(?P<tail>.*)$", re.I)


def _resolve(part: str, first: str) -> str:
    """'how many of them are 3'-0" wide' -> 'how many of the doors listed in the pumphouse door schedule are ...'"""
    if not re.search(r"\b(?:of them|they|them|it|its)\b", part, re.I):
        return part
    m = _SUBJ.match(first.strip().rstrip("?"))
    if not m:
        return part
    noun, tail = m.group("noun"), m.group("tail").strip()
    subj = f"the {noun}" + (f" {tail}" if m.group("verb").lower() in ("are", "is", "were", "was") and tail else
                            f" {m.group('verb')} {tail}" if tail else "")
    return re.sub(r"\bof them\b", f"of {subj}", part, count=1, flags=re.I)


def _sentence(s: str) -> str:
    s = s.strip().rstrip("?.!").strip()
    return s[:1].upper() + s[1:] + "?"


def split_asks(question: str) -> list[str] | None:
    """Two (or three) separate asks joined by 'and' -> the sub-questions, else None. Only splits where the second
    part starts with its own question word ("... and what size ...", "..., and how many of them ..."); "how many
    sinks and wash basins" stays one ask."""
    q = (question or "").strip()
    if not re.match(rf"^\s*{_ASK}\b", q, re.I):
        return None
    pieces = [p for p in _JOIN.split(q) if p and p.strip(" ,;?")]
    if len(pieces) < 2 or len(pieces) > 3:
        return None
    first = pieces[0]
    out = [_sentence(first)] + [_sentence(_resolve(p, first)) for p in pieces[1:]]
    return out if all(len(p) > 8 for p in out) else None


def part_label(sub: str) -> str:
    """A short name for one part's answer row: 'Check valves', 'Discharge header size', '3'-0" wide'."""
    s = sub.strip().rstrip("?").strip()
    m = re.match(r"^how many of (?:the|them)\b.*?\b(?:are|is)\s+(.+)$", s, re.I)
    if m:
        out = m.group(1)
    elif m := _SUBJ.match(s):
        out = m.group("noun")
    elif m := re.match(r"^how many\s+(.+)$", s, re.I):
        out = m.group(1)
    elif m := re.match(r"^what\s+(size|area|length|width|diameter|type|thickness|height|volume)\s+(?:is|are)\s+"
                       r"(?:the\s+)?(.+)$", s, re.I):
        out = f"{m.group(2)} {m.group(1).lower()}"
    elif m := re.match(r"^(?:what|which)\s+(?:is|are)\s+(?:the\s+)?(.+)$", s, re.I):
        out = m.group(1)
    else:
        out = s
    out = out.strip()
    if len(out) > 48:
        out = out[:46].rsplit(" ", 1)[0] + "…"
    return out[:1].upper() + out[1:]
