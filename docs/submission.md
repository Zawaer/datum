# Submission texts (numbers from docs/RESULTS.md, docs/COSTS.md, runs/*.summary.md)

Every number below comes from a run log (`runs/*.jsonl`, rebuilt into `docs/RESULTS.md` by
`BP_OURS_RUN=router_full_test_v4 bash analysis/run_all.sh`) or from `docs/COSTS.md`.
TODO markers remain only for the Nemotron baseline (still running) and the demo / video links.

## Project name (≤ 30 chars)

Blueprints That Talk

_(20 characters)_

## Punchline (≤ 200 chars)

Ask a drawing or BIM model anything, in any language. 88 % right on 25k held-out questions vs 69 % for a frontier model given the same files, every answer proven on the drawing.

_(177 characters)_

## Short version (~600 chars, for quick paste)

Blueprints That Talk answers questions about construction drawings and BIM models, in any language, and draws the proof: counted doors numbered on the plan, rooms outlined with their m², walls lit up in 3D, adding up to the answer. A router picks the cheapest exact method: CAD geometry, IfcOpenShell, a small detector. On all 25,420 held-out test questions: 88.2 % at $0.014 per 1,000, vs 69.0 % for Claude Sonnet 5.5 given the same files at $25.56. Each answer has a calibrated confidence, and below it we say "not sure" instead of guessing. The evaluation was independently audited: no leakage, recount reproduces.

_(617 characters)_

## Description (≤ 5000 chars, markdown)

_Character count of the block between the rules below: 4,260 (limit 5,000)._

---

**Quantity takeoff is slow by hand, and AI is not trusted with it.** A general model that gets a room area wrong looks exactly as confident as when it is right. **Blueprints That Talk** answers questions about drawings and BIM models, in any language, and hands you the proof.

### 1. Accuracy

Held-out test split of the full dataset, split by drawing (every format and language twin of a drawing on the same side). Counts exact, measures within 2 %, abstentions count as wrong.

| | accuracy [95 % CI] | $ / 1,000 q | s / q |
|---|---|---|---|
| **Ours, all 25,420 questions** | **88.2 %** [87.8–88.6] | **$0.014** | **0.03** |
| Claude Sonnet 5.5 + sibling CAD/IFC files* | 69.0 % [60.1–77.6] | $25.56 | 16 |
| Claude Sonnet 5.5, drawing only* | 63.2 % | $13.06 | 13 |
| Claude Haiku 5.5, drawing only* | 60.6 % | $1.21 | 29 |
| Gemini 3.1 Pro, drawing only* | 64.2 % | $52.47 | 31 |
| Nemotron 3.5 Super VL (open), drawing only* | TODO | TODO | TODO |

By source: Swiss apartment plans 100.0 % (8,214), IFC numeric 100 % (600), Finnish raster plans 82.2 % (16,496), IFC free text 36.4 % (110, LLM judge; our weak spot).

\* 400-question sample stratified by source × type, re-weighted to the test mix; cost at API list price. The fair comparison gives Sonnet the same sibling files our solvers read. Gemini cannot take `.ifc` files inline and abstains on those (0.5 % of the mix).

**Independently audited.** Codex (OpenAI) audited the evaluation read-only and a Claude agent re-verified each finding: no split leakage (5,884 drawing groups, 0 straddling), no test data in training, tuning or calibration, no gold lookups at inference, and the headline recount reproduces. We fixed what it found: the baseline now gets sibling files, and cached LLM answers report their real cost.

### 2. Visualising reasoning for verification

The answer is counted out on the drawing: numbered boxes on the plan, each room outlined with its m², contributing IFC elements lit up in 3D and listed by GlobalId. **The evidence adds up to the answer**, so you check the arithmetic, not a picture. Disagree? Untick an item or click one we missed, and the total updates.

Each answer carries a **calibrated confidence**, measured on the test split: raster-plan answers at ≥ 0.95 are right 98.2 % of the time; answering only at ≥ 0.5 keeps 86 % of questions at 95.5 % accuracy and turns 2,027 wrong answers into an honest "not sure".

### 3. Creativity

Instead of asking one big model to guess from pixels, a router sends each question to the cheapest method that can answer it **exactly**:

- **CAD plans:** the PDF's DXF twin gives doors, windows, rooms and apartments by layer; evidence is mapped back onto the PDF.
- **BIM models:** IfcOpenShell counts, areas, lengths and volumes per storey.
- **Raster scans:** a small YOLO11 detector trained only on non-test drawings, with confidence calibrated on dev data.
- **Free text and anything else:** an LLM must answer by citing fact or text-segment ids, so totals are recomputed from what it cited.
- **Any language:** English, Finnish, German, French, Italian, Dutch and more map onto the same typed queries.

In progress: a fine-tuned Qwen3-VL-8B that answers with one box per counted item, as a general grounded fallback. Its first run (70 % on Finnish counts) is below the detector, so the router does not use it for those yet.

### 4. Low inference cost

**$0.014 per 1,000 questions** in API fees on all 25,420 test questions: numeric answers make no paid calls; only 110 free-text questions call Claude Haiku. Local compute (CPU parsing, one small GPU detector) adds about $0.005 per 1,000. That is about 1/1,800 of the fair Sonnet baseline, at 0.03 s instead of ~16 s per answer. Building it all cost about $100, one-off.

### Why it lasts

A better model will still guess a number from pixels; ours reads it from the geometry and hands you the elements behind it. Models are plug-ins behind one evidence contract, and every human correction is a labelled example. For Stoa: a takeoff engine that is cheap enough to run on every drawing, every revision.

Built by Toivo and Rene at Junction 2026. Code: MIT; every number reproducible with `eval.py`. Drawings: Junction dataset, per-file licences, credited in the app.

---

## Technologies

Python, FastAPI, IfcOpenShell, ezdxf, PyMuPDF, Shapely, NumPy, Ultralytics YOLO11, PyTorch, Hugging Face Transformers + PEFT (Qwen3-VL LoRA fine-tuning), vLLM, three.js, Playwright, Claude Sonnet 5.5 / Haiku 5.5 (baseline, LLM judge, free-text answers), Gemini 3.1 Pro and Nemotron 3.5 Super VL (baselines), Codex (independent audit), Claude Code. Training: local RTX 4070 (detector) and cloud GPUs (Verda) for the VLM.

## Links

- Demo: TODO stable public URL
- Source: https://github.com/Zawaer/datum
- Video: TODO upload of `runs/video/` render (script: `docs/video.md`)
- Deck: `docs/deck/deck.pdf`

## Credits (shown on every drawing in the app, deck and video)

Swiss Dwellings v3.0.0 (Archilyse AG, CC BY 4.0) · CubiCasa5K (© 2019 CubiCasa, CC BY-NC-SA 4.0) · Molio Demo-hus
(buildingSMART Community Sample-Test-Files, CC BY 4.0) · BIM-Speed Warmond (TU Berlin, CC BY 4.0) · IFC-Bench v2
questions (S. Hellin, CC BY 4.0). Full per-file credits: `data/<source>/LICENSE.md` in the Junction dataset.
