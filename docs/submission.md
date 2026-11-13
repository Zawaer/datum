# Submission texts (final, numbers from runs/*.summary.md)

Every number below is from a `runs/*.summary.md` written by `eval.py`; see README.md "Reproduce every number".
TODO markers remain only where results are still pending (fine-tuned VLM, final CubiCasa detector run).

## Project name (≤ 30 chars)

Blueprints That Talk

_(20 characters)_

## Punchline (≤ 200 chars)

Ask a drawing or BIM model anything, in any language. 87 % right on 25k held-out questions vs 63 % for a frontier model, with every answer counted out on the drawing, at $0.

_(173 characters)_

## Description (≤ 5000 chars, markdown)

_Character count of the block between the rules below: 4,142 (limit 5,000). Re-count after editing the TODO line._

---

**Quantity takeoff is slow, and AI is not trusted with it.** Counting doors, measuring room areas, summing wall lengths: it is manual work, and a general AI model that gets it wrong looks exactly as confident as when it is right. On our held-out test split, Claude Sonnet 5.5 given the drawing gets Swiss room areas right 38.9 % of the time and BIM volumes 3.8 % of the time.

**Blueprints That Talk answers with proof.** A router sends each question to the cheapest method that can answer it *exactly*, and every method returns its evidence:

- **CAD drawings (PDF + DXF):** doors, windows, fixtures, rooms and apartments read from the CAD layers, mapped onto the PDF the question was asked about.
- **BIM models (IFC):** IfcOpenShell computes counts, net areas, lengths and volumes per storey. The answer carries the GlobalId of every element behind it.
- **Raster plans (scans, images):** a small YOLO11 symbol detector, trained only on open annotations of non-test drawings, boxes every window, door, toilet or sink it counts. A fine-tuned small VLM (Qwen3-VL + LoRA) that answers with one box per item is in training. TODO: VLM result.
- **Anything else:** a grounded fallback makes an LLM answer by citing text segments or boxes, so the total is recomputed from what it cited.
- **Any language:** questions in English, Finnish, German, French, Italian, Danish, Dutch, Estonian… map onto the same typed queries.

**Verify in seconds.** The answer is counted out on the drawing: numbered boxes on the plan, each room outlined with its m² and the list summing to the answer, contributing walls lit up in 3D with their lengths. The evidence adds up to the answer, so you check the arithmetic, not just a picture. Disagree? Untick an item or click one the solver missed, and the total updates. When a solver is not sure, it says "not sure" instead of guessing.

**Cheap by design.** Deterministic code and a small local detector answer every numeric question for $0 marginal cost in 0.03 s on average. Frontier models are an optional fallback, not the engine.

### Results

Held-out test split of the full dataset (split by drawing, so no drawing used in development is scored). Counts exact, measures within 2 %, abstentions count as wrong.

| | accuracy | $ / 1,000 questions | s / question |
|---|---|---|---|
| Claude Sonnet 5.5, drawing + question* | 63.2 % | $13.06 | ~13 |
| Claude Haiku 5.5, drawing + question* | 60.6 % | $1.21 | ~29 |
| **Blueprints That Talk** (all 25,420 questions) | **87.2 %** | **$0.00** | **0.03** |

| | ours | Sonnet* |
|---|---|---|
| Swiss plans, counts (5,580) | 100.0 % | 79.6 % |
| Swiss plans, room areas (2,634) | 99.9 % | 38.9 % |
| IFC counts / areas / volumes / lengths (600) | 100 % | 3.8–42.6 % |
| Finnish raster plans, counts (16,496) | 80.8 % (TODO final run) | 63.6 % |
| IFC-Bench free text (110)** | 34.5 % | 1.8 % |

\* 400-question sample of the test split, stratified by source × type, re-weighted to the test-split mix. Cost at API list price.
\** token-F1 proxy; with an LLM judge our text pipeline scores 27.3 %. Free text is our weakest area.

All numbers come from one script (`eval.py`) that logs every prediction, its cost and its latency; tables by type, source and language are in the repo.

### Why it won't be obsolete next year

A better frontier model will still guess a number from pixels. Ours reads the number from the geometry and hands you the elements behind it, which is what a professional needs before signing off a takeoff. The parts are swappable: when a stronger or cheaper vision model ships, it plugs into the raster and fallback paths, and the exact CAD and BIM paths stay exact. Because every answer is evidence plus arithmetic, a human correction is labelled training data for free.

### For Stoa

The same router + evidence contract runs inside a construction OS: upload a drawing set or a model, ask in the site's language, get takeoff numbers with a review trail, at a cost that allows running it on every drawing, every revision.

Built by Toivo and Rene at Junction 2026. Code: MIT. Drawings: Junction dataset, per-file licences, credited in the app.

---

## Technologies

Python, FastAPI, IfcOpenShell, ezdxf, PyMuPDF, Shapely, NumPy, Ultralytics YOLO11, PyTorch, Hugging Face Transformers + PEFT (Qwen3-VL LoRA fine-tuning), three.js, Playwright, Claude Sonnet 5.5 / Haiku 5.5 (frontier baseline, LLM judge, optional fallback), Claude Code. Training: local RTX 4070 (detector) and a cloud GPU (Verda) for the VLM.

## Links

- Demo: TODO stable public URL
- Source: https://github.com/Zawaer/datum
- Video: TODO upload of `runs/video/` render (script: `docs/video.md`)
- Deck: `docs/deck/deck.pdf`

## Credits (shown on every drawing in the app, deck and video)

Swiss Dwellings v3.0.0 (Archilyse AG, CC BY 4.0) · CubiCasa5K (© 2019 CubiCasa, CC BY-NC-SA 4.0) · Molio Demo-hus
(buildingSMART Community Sample-Test-Files, CC BY 4.0) · IFC-Bench v2 questions (S. Hellin, CC BY 4.0). Full
per-file credits: `data/<source>/LICENSE.md` in the Junction dataset.
