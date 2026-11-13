"""Question -> template key (quoted names and numbers replaced by X)."""
import re

_Q = r"'[^']*'|\"[^\"]*\"|«[^»]*»|„[^“]*“|“[^”]*”|‘[^’]*’"


def template(question: str) -> str:
    t = re.sub(_Q, "X", question)
    t = re.sub(r"\d+(?:[.,]\d+)*", "X", t)
    return t


def slots(question: str) -> list[str]:
    return [m.strip("'\"«»„“”‘’ ") for m in re.findall(_Q, question)]
