"""Official tolerance rules: counts exact, area/length/volume within 2 %, text free-form."""
import re
import unicodedata

REL_TOL = 0.02


def to_number(x):
    if x is None:
        return None
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x)
    # "1,234.5": commas are thousands separators when a dot decimal follows grouped digits
    t = re.search(r"-?\d{1,3}(?:,\d{3})+\.\d+", s)
    if t:
        return float(t.group(0).replace(",", ""))
    # "4,470 SF": comma-grouped digits (groups of exactly three) are thousands, not a decimal comma (4.47)
    t = re.search(r"(?<![\d.,])-?\d{1,3}(?:,\d{3})+(?![\d.,])", s)
    if t:
        return float(t.group(0).replace(",", ""))
    # digit groups may be split by a space, no-break space or narrow no-break space ("2 345,5")
    m = re.search(r"-?\d[\d \u00a0\u202f\u2009]*(?:[.,]\d+)?", s)
    if not m:
        return None
    return float(re.sub(r"[ \u00a0\u202f\u2009]", "", m.group(0)).replace(",", "."))


def norm_text(s) -> str:
    s = unicodedata.normalize("NFKC", str(s)).lower()
    return re.sub(r"[^\w]+", " ", s).strip()


def text_f1(pred, gold) -> float:
    p, g = norm_text(pred).split(), norm_text(gold).split()
    if not p or not g:
        return float(p == g)
    common = sum(min(p.count(t), g.count(t)) for t in set(p))
    if common == 0:
        return 0.0
    prec, rec = common / len(p), common / len(g)
    return 2 * prec * rec / (prec + rec)


def is_correct(qtype: str, pred, gold) -> bool | None:
    """True/False, or None when the solver abstained."""
    if pred is None:
        return None
    if qtype == "count":
        p, g = to_number(pred), to_number(gold)
        return p is not None and g is not None and round(p) == round(g) and abs(p - round(p)) < 1e-6
    if qtype in ("area", "length", "volume"):
        p, g = to_number(pred), to_number(gold)
        if p is None or g is None:
            return False
        if g == 0:
            return abs(p) < 1e-9
        return abs(p - g) / abs(g) <= REL_TOL
    # text / other: exact after normalisation, or token-F1 >= 0.5 (proxy; see README)
    if isinstance(gold, list):
        gold = ", ".join(map(str, gold))
    return norm_text(pred) == norm_text(gold) or text_f1(pred, gold) >= 0.5
