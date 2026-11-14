"""Question -> template key (quoted names and numbers replaced by X)."""
import re

# Quotes must be paired. A straight or curly apostrophe opens a quote only when it is not glued to a word on
# its left (so "What's", "Don't", "d'appartements" never open one) and closes one only when it is not glued
# to a word on its right (so 'Cage d'escalier' and 'IMMUNIZ'N ROOM' stay whole).
_SQ = r"(?<!\w)'(?=\S)(?:.*?\S)?'(?!\w)"
_RSQ = r"(?<!\w)‘(?=\S)(?:.*?\S)?’(?!\w)"
_Q = _SQ + r"|\"[^\"]*\"|«[^»]*»|„[^“]*“|“[^”]*”|" + _RSQ


def template(question: str) -> str:
    t = re.sub(_Q, "X", question)
    t = re.sub(r"\d+(?:[.,]\d+)*", "X", t)
    return t


def slots(question: str) -> list[str]:
    return [m.strip("'\"«»„“”‘’ ") for m in re.findall(_Q, question)]
