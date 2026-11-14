"""Prompt, image budget, target JSON and output parsing shared by training (train/vlm/) and inference.

Keep this file the single source of truth: the model only works if training and inference resize the
image the same way and use the same prompt and output format.

Output format (one JSON object, nothing else):

    {"items": [{"label": "window", "bbox_2d": [x0, y0, x1, y1]}, ...], "count": 3}

Coordinates are integers 0..1000 relative to the image width / height (Qwen3-VL's native grounding
convention, independent of the resize), origin top-left. Items are in reading order (top to bottom,
then left to right). `count` == len(items); it comes last so the model counts what it listed.
"""
from __future__ import annotations

import json
import math
import re

from PIL import Image

Image.MAX_IMAGE_PIXELS = None

SYSTEM = (
    "You read construction drawings and floor plans. For the question, find every instance of the asked "
    "thing on the drawing and reply with JSON only: "
    '{"items": [{"label": <what it is>, "bbox_2d": [x0, y0, x1, y1]}, ...], "count": <number of items>}. '
    "Coordinates are integers 0..1000 relative to the image width and height, origin top-left. "
    "List items top to bottom, left to right. If there are none, reply {\"items\": [], \"count\": 0}."
)

# Qwen3-VL: 16 px patches merged 2x2 -> one visual token per 32x32 px. Images are resized so that both
# sides are multiples of FACTOR and the area is at most the source's pixel budget, here, before the
# processor sees them, so the processor never resizes again (it would round to the same size).
FACTOR = 32
# (min_pixels, max_pixels) per source, chosen with train/vlm/build_dataset.py --measure (see README):
# small CubiCasa scans are upscaled so 20 px symbols get more than one patch; Swiss A3 pages at 150 dpi
# (4.3 MP) are shrunk only as far as their WCs / basins stay ~10 px.
BUDGET = {
    "cubicasa5k": (1024 * 1024, 1280 * 1280),
    "swiss_dwellings": (256 * 256, 1792 * 1792),
    "default": (512 * 512, 1792 * 1792),
}
MIN_PIXELS = 256 * 256


def budget_for(source: str | None) -> tuple[int, int]:
    return BUDGET.get(source or "default", BUDGET["default"])


def target_size(w: int, h: int, max_pixels: int, factor: int = FACTOR, min_pixels: int = MIN_PIXELS):
    """Qwen smart_resize: nearest multiple of `factor` per side, area within [min_pixels, max_pixels]."""
    hb = max(factor, round(h / factor) * factor)
    wb = max(factor, round(w / factor) * factor)
    if hb * wb > max_pixels:
        beta = math.sqrt(h * w / max_pixels)
        hb = max(factor, math.floor(h / beta / factor) * factor)
        wb = max(factor, math.floor(w / beta / factor) * factor)
    elif hb * wb < min_pixels:
        beta = math.sqrt(min_pixels / (h * w))
        hb = math.ceil(h * beta / factor) * factor
        wb = math.ceil(w * beta / factor) * factor
    return wb, hb


def prepare_image(img: Image.Image, budget: tuple[int, int]) -> Image.Image:
    """RGB on white (transparent PNGs exist), resized to the model's grid. Same at train and test time."""
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img)
    img = img.convert("RGB")
    w, h = target_size(*img.size, budget[1], min_pixels=budget[0])
    if (w, h) != img.size:
        img = img.resize((w, h), Image.LANCZOS)
    return img


def user_text(question: str) -> str:
    return question.strip()


def messages(question: str, image=None, answer: str | None = None) -> list[dict]:
    """Chat messages; `image` is a path / URL / PIL image placed before the question."""
    m = [{"role": "system", "content": [{"type": "text", "text": SYSTEM}]},
         {"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": user_text(question)}]}]
    if answer is not None:
        m.append({"role": "assistant", "content": [{"type": "text", "text": answer}]})
    return m


def to_k(b) -> list[int]:
    """Normalised 0..1 bbox -> 0..1000 ints, clamped, at least 1 unit wide."""
    x0, y0, x1, y1 = (min(1000, max(0, round(v * 1000))) for v in b)
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    return [x0, y0, max(x1, x0 + 1), max(y1, y0 + 1)]


def target_json(items: list[tuple[str, list[float]]]) -> str:
    """items: (label, normalised bbox) -> the assistant's reply, items in reading order."""
    its = [(lab, to_k(b)) for lab, b in items]
    its.sort(key=lambda t: ((t[1][1] + t[1][3]) // 2, (t[1][0] + t[1][2]) // 2))
    body = ", ".join('{"label": %s, "bbox_2d": [%d, %d, %d, %d]}' % (json.dumps(lab, ensure_ascii=False), *b)
                     for lab, b in its)
    return '{"items": [%s], "count": %d}' % (body, len(its))


_BOX_RE = re.compile(r'"label"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"bbox_2d"\s*:\s*\[\s*(-?\d+(?:\.\d+)?)\s*,\s*'
                     r'(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]')
_BOX_RE2 = re.compile(r'"bbox_2d"\s*:\s*\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,'
                      r'\s*(-?\d+(?:\.\d+)?)\s*\]')
_COUNT_RE = re.compile(r'"count"\s*:\s*(\d+)')


def parse_output(text: str) -> dict:
    """Model reply -> {"items": [(label, [x0,y0,x1,y1] in 0..1)], "count": int|None, "ok": bool}.

    `ok` is True when the reply was valid JSON of the expected shape. Truncated or slightly broken
    replies are salvaged with regexes (every complete box), so a long list cut off by max_new_tokens
    still yields evidence; `count` is then None.
    """
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    t = re.sub(r"<think>.*?</think>", "", t, flags=re.S).strip()
    items, count, ok = [], None, False
    try:
        d = json.loads(t[t.index("{"): t.rindex("}") + 1])
        its = d.get("items", d if isinstance(d, list) else [])
        for it in its:
            b = it.get("bbox_2d") or it.get("bbox")
            if b and len(b) == 4:
                items.append((str(it.get("label", "")), [min(1.0, max(0.0, float(v) / 1000)) for v in b]))
        count = d.get("count")
        count = int(count) if count is not None else None
        ok = True
    except Exception:  # noqa: BLE001  salvage below
        for m in _BOX_RE.finditer(t):
            items.append((m.group(1), [min(1.0, max(0.0, float(v) / 1000)) for v in m.groups()[1:]]))
        if not items:
            for m in _BOX_RE2.finditer(t):
                items.append(("", [min(1.0, max(0.0, float(v) / 1000)) for v in m.groups()]))
        m = _COUNT_RE.search(t)
        count = int(m.group(1)) if m else None
    # repetition loops (the same box over and over until max_new_tokens) are the main failure of the fine-tuned
    # model on dense classes; two instances never share an identical box, so exact repeats are dropped
    seen, uniq = set(), []
    for lab, b in items:
        k = tuple(round(v, 3) for v in b)
        if k not in seen:
            seen.add(k)
            uniq.append((lab, b))
    return {"items": uniq, "count": count, "ok": ok, "n_raw": len(items)}


def decision_confidence(tokens: list[tuple[str, float]]) -> float | None:
    """Confidence of a reply from per-token log-probs [(token_text, logprob)].

    The count is decided where the model chooses between another item and closing the list; those
    tokens carry a brace / bracket ('}', '},', '}]', ']', ...). Box digits and labels are left out, so
    uncertain box placement doesn't drown the signal. Returns the product of those token probabilities
    (deterministic structure tokens contribute ~1), or None without log-probs.
    """
    if not tokens:
        return None
    lp = sum(l for s, l in tokens if l is not None and any(c in s for c in "{}]"))
    return float(math.exp(lp))


# ---- PaliGemma 2 (Gemma family): native detection format --------------------------------------------
# "<loc{y0}><loc{x0}><loc{y1}><loc{x1}> label ; ..." with 1024 bins per axis (PaliGemma's pretraining
# convention, so the fine-tune builds on its detection skill); "none" for zero items. Count = number of boxes.
PALI_NONE = "none"
_LOC_RE = re.compile(r"<loc(\d{4})><loc(\d{4})><loc(\d{4})><loc(\d{4})>\s*([^;<]*)")


def is_paligemma(model_name_or_type: str | None) -> bool:
    return "paligemma" in (model_name_or_type or "").lower()


def pali_suffix(items: list[tuple[str, list[float]]]) -> str:
    """items (label, normalised bbox) in reading order -> PaliGemma detection string."""
    if not items:
        return PALI_NONE
    out = []
    for lab, (x0, y0, x1, y1) in items:
        q = [min(1023, max(0, round(v * 1023))) for v in (y0, x0, y1, x1)]
        out.append("".join(f"<loc{v:04d}>" for v in q) + f" {lab}")
    return " ; ".join(out)


def pali_from_target(answer_json: str) -> str:
    """Our JSON target (0..1000 ints) -> PaliGemma suffix, same item order."""
    d = json.loads(answer_json)
    return pali_suffix([(it["label"], [v / 1000 for v in it["bbox_2d"]]) for it in d["items"]])


def parse_paligemma(text: str) -> dict:
    items = []
    for m in _LOC_RE.finditer(text):
        y0, x0, y1, x1 = (int(v) / 1023 for v in m.groups()[:4])
        items.append((m.group(5).strip(), [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]))
    t = text.strip()
    ok = bool(items) or t.lower().startswith(PALI_NONE)
    return {"items": items, "count": len(items) if ok else None, "ok": ok}


def pali_decision_confidence(tokens: list[tuple[str, float]]) -> float | None:
    """As decision_confidence, for the PaliGemma format: ';' (another item) vs end of sequence."""
    if not tokens:
        return None
    lp = sum(l for s, l in tokens if l is not None and (";" in s or s in ("<eos>", "</s>") or "none" in s))
    return float(math.exp(lp))
