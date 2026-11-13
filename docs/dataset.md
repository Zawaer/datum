# Stoa – Make Blueprints Talk: dataset notes

Checked the preview zip (478 MB) on Fri 13.11 ~20:45. Full set: 10 GB.
- Preview: https://fwjydgxpttajiqpfmqtj.supabase.co/storage/v1/object/public/stoa-junction-2026/junction-dataset-preview.zip
- Full: https://fwjydgxpttajiqpfmqtj.supabase.co/storage/v1/object/public/stoa-junction-2026/junction-dataset.zip

## What's in it
- Full set: ~14,000 drawings from Europe and the US, ~30 languages, **~120,000 quantity-takeoff questions with ground-truth answers** for ~40% of them. Non-commercial use for Junction only; keep credits (`data/<source>/LICENSE.md`).
- Same name with a different extension = the same drawing in another format. `ifc_models/<model>_<level>.pdf` floor plans are rendered from `<model>.ifc`.
- Preview: 924 files: 374 jpg, 306 png, 123 pdf, 66 dxf, 20 dwg, **14 ifc**, 10 svg + `questions.jsonl` (7,990 questions)

| source | what |
|---|---|
| cubicasa5k | Finnish real-estate floor plans (PNG; CC BY-NC-SA) |
| swiss_dwellings | Swiss apartment floors (PDF, DXF, PNG) |
| opening_design | real drawing sets + CAD of a US architecture practice, original folders (incl. "bad IFC models – for autopsy only") |
| ifc_models | open IFC building models + floor plans rendered from them |
| ifc_bench | IFC models with the IFC-Bench v2 questions |
| habs | US historic measured drawings (Library of Congress) |
| finna | Helsinki City Archives + Architecture & Design Museum |
| europeana, wikimedia | European/UK/US plans |

## Questions (`questions.jsonl`: path, question, answer, unit, type)
Preview mix: count 6,076 · area 1,599 · text 265 · volume 34 · length 16. By source: cubicasa5k 4,270, swiss 2,358, ifc_models 1,049, ifc_bench 249, opening_design 64.
**Scoring: counts must be exact; areas, lengths and volumes within 2%; text is free-form.**
Many questions come in the drawing's own language (fi, et, da, de…) plus an English version.

Examples:
- cubicasa PNG: "How many windows are shown on this floor plan?" → 13 (also in Finnish); "How many toilet bowls…" → 2; sinks/basins (a double bowl counts as one) → 3
- swiss PDF: "Net floor area of room 4.23 ('Bad') in m²?" → 4.32
- IFC: "Total length of all walls on '1. Sal'?" → 222.79 m; wall net volume (Danish, German); Estonian room net area → 5.58 m²
- ifc_bench text: "What railings are installed?", "What MEP systems are present?"

## Why this matters
- **Ground truth for ~120k questions** → we can report a real accuracy table (by type, source and language) and compare against a frontier-model baseline. That's the "honest numbers" edge.
- **IFC = exact answers + 3D.** IFC questions can be answered deterministically with IfcOpenShell (geometry and quantities) and shown in 3D (web-ifc / That Open Engine / three.js) with the elements highlighted.
- **Raster plans = counting with CV.** Symbol detection (YOLO, as in Bananagrams) + a VLM for room labels, with bounding boxes as the "where it came from" evidence. Batch on cloud GPUs to keep cost low (25% of the score).
