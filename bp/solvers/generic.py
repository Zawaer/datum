"""Generic fallback solver: any drawing, any question, always with evidence on the drawing.

1. Text layer first (vector PDF / SVG / DXF): words with positions are grouped into layout segments
   (table-row fragments, labels; bp/generic/text.py) and listed one baseline row per line with ids.
   An LLM answers *by citing segment ids*: for counts and sums it lists one item per counted row
   with the value it read, and the answer is recomputed here as the sum of those values, so the
   evidence boxes reproduce the arithmetic. Values are checked against the cited text.
2. Grounded vision when there is no text layer (scans, PNG/JPG) or the answer needs drawn symbols:
   a VLM boxes every instance of the target on each tile of the page (bp/generic/vision.py);
   count = number of boxes, each box is one evidence item. Two passes at different scales give an
   agreement score used as confidence.
3. Other questions on rasters: the VLM answers and boxes where it read the answer.

variant "<text>+<vision>": "haiku+haiku" (default: no GPU needed, ~$0.003-0.01 per question),
"haiku+sonnet" (better grounding, ~$0.03/q), "haiku+qwen" / "qwen+qwen" (local Qwen3-VL, $0 API; needs
~4 GB free VRAM, else it falls back to haiku). Paid vision is capped per question: page rendered at <= 2900 px
so the tiled pass is <= 6 calls, plus one whole-page call (~$0.01 on haiku).
"""
from __future__ import annotations

import re
import threading

from bp.data import data_root
from bp.generic import llm, text as T, vision as V

TEXT_SYSTEM = (
    "You answer questions about construction drawings from the drawing's extracted text layer. "
    "Reply with one JSON object only."
)

TEXT_PROMPT = """Question: {question}
{unit_line}
Below is the text layer of the drawing ({src}), one line per text baseline, top to bottom.
Each line is "y=<top, % of page height>: [id]@<x, % of page width> text ...". Inside a segment, " | "
separates table cells. Segments on one line with the same y usually belong to one table row; tables
side by side share lines, so use the x positions and the column headers to tell tables apart.

{layout}

Answer using only this text. Reply with JSON:
{{"mode": "text", "op": "count" | "sum" | "read",
  "items": [{{"ids": [<segment ids of this item>], "value": <number or string>, "what": "<short name>"}}],
  "answer": <final answer>, "confidence": "high" | "medium" | "low", "explanation": "<one line>"}}
Rules:
- op "count": one item per counted thing (e.g. one per schedule row that matches), cite the ids of that
  row's segments, value = how many things the item contributes (1 for a row, or the number in a
  Count/Quantity column if the schedule gives quantities). answer = sum of values.
- op "sum": one item per number added up (e.g. each room's area), value = that number as read; answer = sum.
- op "read": the answer is read directly (a name, a dimension, a code, one number): one item citing where
  it was read, value = the text read. Copy dimensions and codes exactly as printed.
- Keep "answer" short, in the drawing's own words (e.g. "C3 - acoustic tile", "2' - 6 1/2\"",
  "4 doors, 120 SF"): no full sentences, no commentary.
- Be exhaustive: check every row of the relevant table, not just the first ones.
- If the question is about graphical symbols that are drawn, not written (e.g. counting toilets or
  windows drawn on a plan), reply {{"mode": "vision", "target": "<short English name of one instance to
  box, e.g. 'toilet (water closet) symbol in plan view'>", "size": "small" | "large", "region_ids": [<ids of the title / labels of
  the view the question is about, if any>]}}.
- If the text does not contain the answer, reply {{"mode": "none", "explanation": "..."}}.
"""

TARGET_PROMPT = """A user asks about a drawing (floor plan, construction drawing or scan): "{question}"
To answer, a vision model will draw a box around every instance of the thing being counted.
Reply with JSON only: {{"target": "<short English description of ONE instance as it looks on a drawing,
with the usual plan symbol or room label, e.g. 'toilet bowl (WC) symbol', 'window opening in an exterior
wall', 'room labelled MH (bedroom)'>", "label": "<one or two words>",
"size": "small" if one instance is a small symbol or label on the sheet, "large" if it is a whole room, view,
plan, storey or building}}"""

CONF = {"high": 0.85, "medium": 0.6, "low": 0.3}


def _num(x):
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(x or ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _fmt(v):
    return int(round(v)) if v is not None and abs(v - round(v)) < 1e-9 else v


class GenericSolver:
    def __init__(self, variant=None, text_budget_chars: int = 60000):
        tb, _, vb = (variant or "haiku+haiku").partition("+")
        self.text_backend = tb or "haiku"
        self.vision_backend = vb or tb or "qwen"
        self.budget = text_budget_chars
        self.root = data_root()
        self._targets: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------------------ LLM plumbing
    def _ask_text(self, prompt: str, tag: str):
        """(reply text, cost, gpu_s) on the text backend."""
        if self.text_backend == "qwen":
            from bp.generic import qwen

            t, g = qwen.generate(TEXT_SYSTEM + "\n\n" + prompt, [], max_new_tokens=2048)
            return t, 0.0, g
        r = llm.ask(prompt, model=self.text_backend, system=TEXT_SYSTEM, tag=tag)
        return r["text"], r["cost_usd"], 0.0

    def _target(self, question: str):
        """Question -> what to box (cached per question template: one call per question form)."""
        from bp.templates import template

        key = template(question)
        with self._lock:
            if key in self._targets:
                return self._targets[key], 0.0, 0.0
        txt, cost, gs = self._ask_text(TARGET_PROMPT.format(question=question), "target")
        d = llm.parse_json(txt) or {}
        if not isinstance(d, dict) or not d.get("target"):
            d = {"target": re.sub(r"(?i)^how many |\?.*$", "", question).strip()[:80], "label": "item"}
        with self._lock:
            self._targets[key] = d
        return d, cost, gs

    # -------------------------------------------------------------------------------- text path
    def _text(self, q, path):
        pages = T.pick_pages(path, q["question"])
        segs, nid = [], 0
        for p in pages:
            ss, _ = T.layout(path, p)
            for s in ss:  # renumber across pages (layout() is cached, so copy)
                segs.append(T.Segment(nid, s.page, s.bbox, s.cells, s.row))
                nid += 1
        if sum(len(s.text) for s in segs) < 40:
            return None, 0.0, 0.0  # no usable text layer
        shown = T.relevant(segs, q["question"], self.budget)
        unit = q.get("unit")
        unit_line = f"Answer unit: {unit}." if unit and unit not in ("count", "None", None) else ""
        prompt = TEXT_PROMPT.format(question=q["question"], unit_line=unit_line, layout=T.to_prompt(shown),
                                    src=f"{q['ext'].upper()}, {len(pages)} page(s) shown")
        txt, cost, gs = self._ask_text(prompt, "text")
        d = llm.parse_json(txt)
        if not isinstance(d, dict):
            return {"mode": "error", "raw": txt[-500:]}, cost, gs
        d["_segs"] = {s.id: s for s in segs}
        d["_raw"] = txt[-1500:]
        return d, cost, gs

    def _text_result(self, q, d):
        segs = d["_segs"]
        op = d.get("op", "read")
        items = d.get("items") or []
        ev, grounded, checked, bad_ids = [], 0, 0, 0
        values = []
        for i, it in enumerate(items, 1):
            if not isinstance(it, dict):
                continue
            ids = [int(x) for x in (it.get("ids") or []) if str(x).lstrip("-").isdigit()]
            ss = [segs[x] for x in ids if x in segs]
            bad_ids += len(ids) - len(ss)
            if not ss:
                continue
            txt = " ".join(s.text for s in ss)
            v = it.get("value")
            if op in ("count", "sum"):
                nv = _num(v)
                if nv is None:
                    continue
                values.append(nv)
                if op == "sum" or nv != 1:
                    checked += 1
                    grounded += T.value_in_text(nv, txt)
            # one evidence item per segment page; the box covers the item's segments on that page
            for pg in sorted({s.page for s in ss}):
                bb = T._union([s.bbox for s in ss if s.page == pg])
                ev.append({"kind": "text" if op == "read" else "box", "file": q["path"], "page": pg,
                           "bbox": [round(x, 5) for x in bb],
                           "label": f"{it.get('what') or 'item'} {i}: '{txt[:80]}'"
                           if op != "read" else f"label read: '{txt[:100]}'",
                           "value": _fmt(values[-1]) if op in ("count", "sum") else None})
        conf = CONF.get(str(d.get("confidence", "")).lower(), 0.5)
        stated = d.get("answer")
        if op in ("count", "sum"):
            if not values:
                return None
            ans = _fmt(sum(values))
            sn = _num(stated)
            if sn is not None and abs(sn - sum(values)) > 1e-6 * max(1, abs(sn)):
                conf *= 0.6  # the model's own total disagrees with its itemisation
            if q.get("type") in ("text", "other") and stated is not None:
                ans = stated
        else:
            ans = stated
            if ans is None and items:
                ans = items[0].get("value")
            if ans is not None and ev and isinstance(ans, (str, int, float)):
                # the answer should be visible in what was cited
                cited = " ".join(e["label"] for e in ev).lower()
                toks = [t for t in re.findall(r"[\w'\"-]+", str(ans).lower()) if len(t) > 1]
                if toks and sum(t in cited for t in toks) / len(toks) < 0.5:
                    conf *= 0.7
        if checked:
            conf *= 0.4 + 0.6 * grounded / checked
        if bad_ids:
            conf *= 0.7
        if not ev:
            conf *= 0.5
        return {"answer": ans, "confidence": round(conf, 3), "evidence": ev,
                "explanation": str(d.get("explanation") or "")[:200]}

    # ------------------------------------------------------------------------------ vision path
    SCALE_RX = re.compile(r"\d\s*/?\s*\d*\s*\"\s*=\s*1\s*'|\bscale\b|\b1\s*:\s*\d{1,4}\b", re.I)

    def _view_region(self, segs, ids, page):
        """Region of the view whose title segments are `ids`. A view title sits under the bottom-left
        of its view; the view ends where the neighbouring views' titles / scale notes begin."""
        tb = T._union([segs[i].bbox for i in ids if segs[i].page == page])
        x0, y0, x1, y1 = max(0.0, tb[0] - 0.03), max(0.0, tb[1] - 0.45), min(1.0, tb[0] + 0.4), min(1.0, tb[3] + 0.02)
        others = [s for s in segs.values() if s.page == page and s.id not in ids and self.SCALE_RX.search(s.text)]
        for s in others:
            if s.bbox[1] < tb[1] - 0.02 and s.bbox[3] > y0 and s.bbox[0] < x1 and s.bbox[2] > x0 \
                    and abs(s.bbox[0] - tb[0]) < 0.1:  # the title of the view above
                y0 = max(y0, s.bbox[3] + 0.005)
            if abs(s.bbox[1] - tb[1]) < 0.03 and tb[0] + 0.05 < s.bbox[0] < x1:  # the title of the view to the right
                x1 = s.bbox[0] - 0.01
        return (x0, y0, x1, y1)


    def _vision_count(self, q, path, page, target, label, region=None, size="small"):
        try:
            return self._vision_count_on(q, path, page, target, label, region, size)
        except Exception as e:  # noqa: BLE001  local VLM unavailable (no GPU / weights): use the paid path
            if self.vision_backend != "qwen":
                raise
            self.vision_backend = "haiku"
            out = self._vision_count_on(q, path, page, target, label, region, size)
            out["explanation"] += f" [local VLM unavailable: {type(e).__name__}]"
            return out

    def _vision_count_on(self, q, path, page, target, label, region=None, size="small"):
        if size == "large":  # whole views / rooms / storeys: never cut them into tiles
            img = T.render(path, page, max_side=1600)
            if img is None:
                return None
            a = V.count(img, target, self.vision_backend, tile=1600, label=label, region=region, max_area=0.97)
            b = V.count(img.resize((img.width * 2 // 3, img.height * 2 // 3)), target, self.vision_backend,
                        tile=1600, min_side=0, label=label, region=region, max_area=0.97)
            return self._count_result(q, page, target, label, a, b)
        paid = self.vision_backend != "qwen"
        if paid:  # cost cap: <= 6 tiles for pass A, one whole-page call for pass B
            img = T.render(path, page, max_side=2900 if region is None else 4800)
            if img is None:
                return None
            a = V.count(img, target, self.vision_backend, tile=1280, label=label, region=region)
            whole = img if region is None else img.crop(tuple(round(v * s) for v, s in zip(region, img.size * 2)))
            whole = whole.copy()
            whole.thumbnail((1568, 1568))
            b = V.count(whole, target, self.vision_backend, tile=1600, min_side=0, label=label)
            if region is not None:
                rw, rh = region[2] - region[0], region[3] - region[1]
                b["boxes"] = [[region[0] + x0 * rw, region[1] + y0 * rh, region[0] + x1 * rw, region[1] + y1 * rh]
                              for x0, y0, x1, y1 in b["boxes"]]
            return self._count_result(q, page, target, label, a, b)
        img = T.render(path, page, max_side=4096 if region is None else 6144)
        if img is None:
            return None
        # pass A: native-ish scale; pass B: different scale, for an agreement-based confidence
        side = max(img.size) * (1 if region is None else max(region[2] - region[0], region[3] - region[1]))
        a = V.count(img, target, self.vision_backend, tile=1280, label=label, region=region)
        b = V.count(img, target, self.vision_backend, tile=1280, min_side=1400, label=label, region=region) \
            if side < 1400 else V.count(img, target, self.vision_backend, tile=960, label=label, region=region)
        return self._count_result(q, page, target, label, a, b)

    def _count_result(self, q, page, target, label, a, b):
        agree = V.match_f1(a["boxes"], b["boxes"])
        same = len(a["boxes"]) == len(b["boxes"])
        conf = round(0.15 + 0.55 * agree + 0.2 * same, 3)
        lab = label or "item"
        ev = [{"kind": "box", "file": q["path"], "page": page, "bbox": bb, "label": f"{lab} {i}", "value": 1}
              for i, bb in enumerate(a["boxes"], 1)]
        return {"answer": len(a["boxes"]), "confidence": conf, "evidence": ev,
                "cost_usd": a["cost_usd"] + b["cost_usd"], "gpu_s": a["gpu_s"] + b["gpu_s"],
                "explanation": f"{len(a['boxes'])} x '{target}' boxed by {self.vision_backend} "
                               f"(second pass found {len(b['boxes'])}, box agreement {agree:.2f})"}

    def _vision_read(self, q, path, page):
        try:
            return self._vision_read_on(q, path, page)
        except Exception:  # noqa: BLE001
            if self.vision_backend != "qwen":
                raise
            self.vision_backend = "haiku"
            return self._vision_read_on(q, path, page)

    def _vision_read_on(self, q, path, page):
        img = T.render(path, page, max_side=2048)
        if img is None:
            return None
        ans, boxes, conf, cost, gs, raw = V.read(img, q["question"], self.vision_backend, q.get("unit"))
        ev = [{"kind": "text", "file": q["path"], "page": page, "bbox": [round(min(max(v, 0), 1), 5) for v in b],
               "label": lab or "read here"} for b, lab in boxes]
        if conf is None:
            conf = 0.35 if ans is not None and ev else 0.15
        if ans is not None and q.get("type") in ("count", "area", "length", "volume"):
            n = _num(ans)
            ans = _fmt(n) if n is not None else None
        return {"answer": ans, "confidence": conf if ev else conf * 0.5, "evidence": ev, "cost_usd": cost,
                "gpu_s": gs, "raw": raw[-800:], "explanation": f"read by {self.vision_backend}"}

    # ------------------------------------------------------------------------------------- main
    def __call__(self, q):
        path = str(self.root / q["path"])
        ext = q.get("ext") or path.rsplit(".", 1)[-1].lower()
        qtype = q.get("type")
        if not qtype:
            from bp.router import guess_type

            qtype = guess_type(q["question"])
            q = {**q, "type": qtype}
        cost = gpu = 0.0
        method, target, label, page, region, size = None, None, None, 0, None, "small"
        out = None
        if ext not in T.RASTER:
            d, c, g = self._text(q, path)
            cost += c
            gpu += g
            if d and d.get("mode") == "text":
                out = self._text_result(q, d)
                method = f"generic-text-{self.text_backend}"
                if out:
                    out["raw"] = d.get("_raw")
            elif d and d.get("mode") == "vision":
                target, size = d.get("target"), d.get("size", "small")
                ids = [i for i in d.get("region_ids") or [] if i in d["_segs"]]
                page = d["_segs"][ids[0]].page if ids else 0
                if ids:
                    region = self._view_region(d["_segs"], ids, page)
        if out is None:
            if qtype == "count":
                if target is None:
                    t, c, g = self._target(q["question"])
                    cost += c
                    gpu += g
                    target, label, size = t.get("target"), t.get("label"), t.get("size", "small")
                out = self._vision_count(q, path, page, target, label, region, size)
                method = f"generic-ground-{self.vision_backend}"
            else:
                out = self._vision_read(q, path, page)
                method = f"generic-read-{self.vision_backend}"
        if out is None:
            return {"answer": None, "confidence": 0.0, "evidence": [], "cost_usd": cost, "method": "generic-none",
                    "explanation": "no text layer and no renderable page"}
        out["cost_usd"] = round(cost + out.get("cost_usd", 0.0), 6)
        out["gpu_s"] = round(gpu + out.get("gpu_s", 0.0), 2)
        out["method"] = method
        return out
