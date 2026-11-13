# Solver contract and evidence format

Every solver is a callable `solver(q) -> dict`. `q` is a question dict from `bp.data.load_questions()`
(`path`, `question`, `type`, `unit`, `source`, `ext`, `id`, `split`).

```python
{
  "answer": 13,              # number for count/area/length/volume, str for text; None = abstain
  "confidence": 0.95,        # 0..1, honest; the router abstains / falls back below a threshold
  "method": "swiss-dxf",     # short id of the path that produced the answer
  "cost_usd": 0.0,           # marginal inference cost of this answer (API spend; local compute ~0)
  "explanation": "28 window symbols on layer WINDOW",   # one line, human readable, shown in the UI
  "evidence": [ ... ],       # items below; the UI draws them
}
```

## Evidence items

Coordinates for 2D items are **normalised to the rendered page / image: x, y in 0..1, origin top-left**,
so the UI can draw them over a render of any size. `file` is the dataset-relative path of the drawing
the coordinates refer to (usually `q["path"]`; may be a twin, e.g. the PNG of a PDF).

- `{"kind": "box", "file": ..., "page": 0, "bbox": [x0, y0, x1, y1], "label": "window 3", "value": null}`
  one counted item. Number them 1..n in `label` order.
- `{"kind": "polygon", "file": ..., "page": 0, "points": [[x, y], ...], "label": "2.10 Zimmer", "value": 16.78}`
  a measured region (room, apartment); `value` is its contribution to the answer.
- `{"kind": "text", "file": ..., "page": 0, "bbox": [...], "label": "label read: '16.78 m²'"}`
  a piece of text the answer was read from.
- `{"kind": "ifc", "file": "data/.../x.ifc", "guids": ["2O2Fr$t4X7Zf8NOew3FLOH", ...], "label": "IfcWall 'Basic Wall:Interior'", "value": 4.21}`
  IFC elements (GlobalIds) that the UI lights up in 3D; `value` = this element's contribution.

The sum / count of `value`s over the evidence should reproduce the answer, so a reviewer can check
the arithmetic, not just the picture.
