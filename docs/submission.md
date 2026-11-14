# Submission texts (numbers from docs/RESULTS.md, docs/COSTS.md, runs/*.summary.md)

Every number below comes from a run log (`runs/*.jsonl`, rebuilt into `docs/RESULTS.md` by
`BP_OURS_RUN=router_full_test_v6 bash analysis/run_all.sh`), from `docs/COSTS.md`, or from the verification
reports (`runs/crosscheck_test.summary.md`, `runs/crosscheck_vlm_test.summary.md`, `docs/EVIDENCE_QUALITY.md`, `docs/ROBUSTNESS.md`, `docs/PROVENANCE.md`).
TODO markers remain only for the demo / video links.

## Project name (≤ 30 chars)

Blueprints That Talk

_(20 characters)_

## Punchline (≤ 200 chars)

Ask a drawing or BIM model anything, in any language. 89.5 % right on 25k held-out questions vs 69.8 % for a frontier model given the same files, every answer shown on the drawing.

_(181 characters)_

## Short version (~600 chars, for quick paste)

Blueprints That Talk answers questions about construction drawings and BIM models (tested in six languages) and draws the proof: counted doors numbered on the plan, rooms outlined with their m², walls lit up in 3D, adding up to the answer. A router picks the cheapest exact method: CAD geometry, IfcOpenShell, a small detector. On all 25,420 held-out test questions (every one, not a sample): 89.5 % at $0.013 per 1,000, vs 69.8 % for Claude Sonnet 5.5 given the same files at $25.76. Each answer carries a calibrated confidence; numeric ones an independent cross-check. The evaluation was cross-audited by a second AI agent (Codex): no leakage, recount reproduces.

_(665 characters)_

## Description (≤ 5000 chars, markdown)

_Character count of the block between the rules below: 4,649 (limit 5,000)._

---

**Quantity takeoff is slow by hand, and AI is not trusted with it.** A general model that gets a room area wrong looks exactly as confident as when it is right. **Blueprints That Talk** answers questions about drawings and BIM models, in six languages tested so far, and hands you the proof.

### 1. Accuracy

Held-out test split, split by whole drawing (hash of the drawing id, 20 % test; every format and language twin on the same side). Counts exact, measures within 2 %, abstentions count as wrong.

| | accuracy [95 % CI] | $ / 1,000 q |
|---|---|---|
| **Ours, all 25,420 questions** | **89.5 %** [89.1–89.8] | **$0.013** |
| Claude Sonnet 5.5 + sibling CAD/IFC files* | 69.8 % [60.9–78.4] | $25.76 |
| Gemini 3.1 Pro, drawing only* | 64.2 % | $52.47 |
| Claude Sonnet 5.5, drawing only* | 63.2 % | $13.06 |
| Claude Haiku 5.5, drawing only* | 60.6 % | $1.21 |
| Nemotron 3.5 Super VL (open)* | 49.0 % | $2.59 |

By source: Swiss plans 99.95 % (8,214), IFC numeric 100 % (600), Finnish raster plans 84.2 % (16,496), IFC free text 38.2 % (110, LLM judge; our weak spot).

\* 400-question sample stratified by source × type (±~13 pp per cell), re-weighted to the test mix. The fair comparison gives Sonnet the same sibling files our solvers read.

**Cross-audited by a second AI agent (Codex).** Codex (OpenAI) audited the evaluation and a Claude agent re-verified each finding: no split leakage, no test data in training, tuning or calibration, no gold lookups at inference; the recount reproduces.

### 2. Visualising reasoning for verification

The answer is counted out on the drawing: numbered boxes, rooms outlined with their m², IFC elements lit up in 3D by GlobalId. Four layers:

- **Evidence that adds up.** Untick an item or click a missed one and the total updates. The boxes themselves are right: >90 % precision and recall against independent gold; only ~2.5 % of right counts are right by luck.
- **Calibrated confidence**, measured on test: answering only at ≥ 0.5 keeps 87.5 % of questions at 95.4 % and turns 1,658 wrong answers into an honest "not sure" (Finnish plans: 92.8 % when answered, 19 % declined; Swiss and IFC numeric: 99.9–100 %, none declined).
- **Independent cross-check.** A second method re-derives 98 % of numeric answers (PDF re-read for CAD plans, the SVG sheet for IFC, a fine-tuned vision model for scans). Where they agree, Swiss and IFC answers were right 99.98 % of the time (all but 2 of 8,184); it caught a real error in our own CAD reading of an apartment area. On conflict, confidence is halved and both readings are shown.
- **Provenance.** Every number in an LLM-written answer is traced to the facts it cites, or flagged.

Robustness: 12,654 language-twin pairs agree 100 %; held-out typed paraphrases 81 % vs 82 % for the original wording (49 % before our normaliser); 50/50 must-abstain questions abstain.

### 3. Creativity

Stoa asks for approaches next year's frontier models won't make obsolete: "hybrids of frontier models + CV + 3D/geometry + small fine-tuned models". That is this system. A router sends each question to the cheapest method that answers it **exactly**:

- **CAD plans:** the PDF's DXF twin gives doors, windows, rooms by layer; evidence is mapped back onto the PDF.
- **BIM models:** IfcOpenShell counts, areas, lengths, volumes per storey.
- **Raster scans:** a YOLO11m detector trained only on non-test drawings, confidence calibrated on dev.
- **Small fine-tuned VLM:** a fine-tuned 8B vision model (Qwen3-VL-8B LoRA, 75 % alone) acts as an independent second opinion: when it agrees (74 % of raster questions), answers are 94.6 % right.
- **Claude Haiku 5.5, a small frontier LLM, only for free text** (the 110 free-text questions, 0.4 % of test): answers by citing fact ids, and a normaliser that maps free wording onto exact queries using only names in the drawing.

### 4. Low inference cost

**$0.013 per 1,000 questions** in API fees on all 25,420 test questions: numeric answers make no paid calls. Local compute adds about $0.005 per 1,000. About 1/1,900 of the fair Sonnet baseline, at 0.04 s instead of ~16 s per answer.

### Why it lasts

A better model will still guess a number from pixels; ours reads it from the geometry and hands you the elements behind it. Models are plug-ins behind one evidence contract, and every human correction is a labelled example. For Stoa: a takeoff engine cheap enough to run on every drawing, every revision.

Built by Toivo and Rene at Junction 2026. Code: MIT; reproducible: dataset + one command (`eval.py`), no API keys needed for numeric answers. Drawings: Junction dataset, per-file licences, credited in the app.

---

## Technologies

Python, FastAPI, IfcOpenShell, ezdxf, PyMuPDF, Shapely, NumPy, Ultralytics YOLO11m, PyTorch, Hugging Face Transformers + PEFT (Qwen3-VL LoRA fine-tuning), vLLM, three.js, Playwright, Claude Sonnet 5.5 / Haiku 5.5 (baseline, LLM judge, free-text answers), Gemini 3.1 Pro and Nemotron 3.5 Super VL (baselines), Codex (cross-audit of the evaluation), Claude Code. Training: local RTX 4070 (detector) and cloud H100s (Verda) for the VLM.

## Links

- Demo: TODO stable public URL
- Source: https://github.com/Zawaer/datum
- Video: TODO upload of `runs/video/` render (script: `docs/video.md`)
- Deck: `docs/deck/deck.pdf`

## Credits (shown on every drawing in the app, deck and video)

Swiss Dwellings v3.0.0 (Archilyse AG, CC BY 4.0) · CubiCasa5K (© 2019 CubiCasa, CC BY-NC-SA 4.0) · Molio Demo-hus
(buildingSMART Community Sample-Test-Files, CC BY 4.0) · BIM-Speed Warmond (TU Berlin, CC BY 4.0) · IFC-Bench v2
questions (S. Hellin, CC BY 4.0). Full per-file credits: `data/<source>/LICENSE.md` in the Junction dataset.
