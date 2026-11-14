# Submission texts (numbers from docs/RESULTS.md, docs/COSTS.md, runs/*.summary.md)

Every number below comes from a run log (`runs/*.jsonl`, rebuilt into `docs/RESULTS.md` by
`BP_OURS_RUN=router_full_test_v7 bash analysis/run_all.sh`), from `docs/COSTS.md`, or from the verification
reports (`runs/crosscheck_test.summary.md`, `runs/crosscheck_vlm_test_v7.summary.md`, `docs/EVIDENCE_QUALITY.md`, `docs/ROBUSTNESS.md`, `docs/PROVENANCE.md`).
TODO markers remain only for the demo / video links.

## Project name (≤ 30 chars)

Blueprints That Talk

_(20 characters)_

## Punchline (≤ 200 chars)

Ask a drawing or BIM model anything, in any language. 90.0 % right on 25k held-out questions vs 69.8 % for a frontier model given the same files, every answer shown on the drawing.

_(181 characters)_

## Short version (~600 chars, for quick paste)

Blueprints That Talk answers questions about construction drawings and BIM models, typed or spoken in six tested languages, and shows the proof: the plan rises into 3D with the counted doors lit and numbered, items light up one by one as the count ticks up, rooms are outlined with their m². A router picks the cheapest exact method: CAD geometry, IfcOpenShell, a small detector, our fine-tuned vision model as a second opinion. On all 25,420 held-out test questions: 90.0 % at $0.013 per 1,000, vs 69.8 % for Claude Sonnet 5.5 given the same files at $25.76. Calibrated confidence, an independent cross-check, an audited evaluation and 278 automated tests.

_(657 characters)_

## Description (≤ 5000 chars, markdown)

_Character count of the block between the rules below: 4,648 (limit 5,000)._

---

**Quantity takeoff is slow by hand, and AI is not trusted with it.** A general model that gets a room area wrong looks exactly as confident as when it is right. **Blueprints That Talk** answers questions about drawings and BIM models (six languages tested, typed or spoken) and shows the proof: ask "how many doors?" and the 2D CAD plan rises into a 3D building with the counted doors lit and numbered.

**Outcome:** 90.0 % [89.7–90.4] on all 25,420 held-out test questions at **$0.013 per 1,000**, vs 69.8 % for Claude Sonnet 5.5 given the same files at $25.76.

### 1. Accuracy

Split by whole drawing (hash of id, 20 % test; formats and language twins stay together). Counts exact, measures within 2 %, abstentions count as wrong.

| | accuracy [95 % CI] | $ / 1,000 q |
|---|---|---|
| **Ours, all 25,420 questions** | **90.0 %** [89.7–90.4] | **$0.013** |
| Claude Sonnet 5.5 + sibling CAD/IFC files* | 69.8 % [60.9–78.4] | $25.76 |
| Gemini 3.1 Pro, drawing only* | 64.2 % | $52.47 |
| Claude Sonnet 5.5, drawing only* | 63.2 % | $13.06 |
| Claude Haiku 5.5, drawing only* | 60.6 % | $1.21 |
| Nemotron 3.5 Super VL (open)* | 49.0 % | $2.59 |

By source: Swiss plans 99.95 % (8,214), IFC numeric 100 % (600), Finnish raster plans 85.1 % (16,496; flip test-time augmentation added today, 84.2 → 85.1), IFC free text 38.2 % (110, LLM judge; our weak spot).

\* 400-question sample stratified by source × type (±~13 pp per cell), re-weighted to the test mix.

A second AI agent (Codex) audited the evaluation: no leakage, no test data in training or tuning; the recount reproduces. A fresh clone reproduces the headline with no API keys.

### 2. Visualising reasoning for verification

- **Proof on the drawing:** numbered boxes, rooms outlined with their m², IFC elements lit in 3D (exploded storeys, x-ray). Untick or add an item and the total updates. Boxes: >90 % precision and recall vs independent gold.
- **X-ray count:** items light up one by one as the number ticks up, beside a "ghost" line of what five frontier models answered and how far off each is.
- **Calibrated confidence:** answering only at ≥ 0.5 keeps 87.6 % of questions at 95.8 % and turns 1,594 wrong answers into an honest "not sure" (Finnish plans: 93.4 % when answered).
- **Independent cross-check:** a second method re-derives 98 % of numeric answers; where they agree, Swiss and IFC answers are right 99.98 % of the time; it caught a real error in our own CAD reading. On conflict, confidence is halved and both readings are shown.
- **Provenance:** every number in an LLM-written answer is traced to the facts it cites, or flagged.
- **Sign-off:** room heat-map and a printable takeoff sheet.

Robustness: 12,654 language-twin pairs agree 100 %; held-out typed paraphrases 80 % (49 % before our normaliser); 49/50 must-abstain questions abstain.

### 3. Creativity

Stoa asks for "hybrids of frontier models + CV + 3D/geometry + small fine-tuned models". A router sends each question to the cheapest method that answers it **exactly**:

- **CAD plans:** the DXF twin gives doors, windows, rooms by layer, mapped back onto the PDF and raised into 3D.
- **BIM:** IfcOpenShell counts, areas, lengths, volumes per storey.
- **Comparisons** ("which room is the largest?", "is apartment B bigger than A?") answered from the geometry, arithmetic shown.
- **Raster scans:** a YOLO11m detector trained only on non-test drawings.
- **Our fine-tuned 8B vision model** (Qwen3-VL LoRA) is a second opinion: when it agrees (74 % of raster questions), answers are 94.9 % right. It now also runs live on a Verda GPU for users' own uploads.
- **Claude Haiku 5.5 only for free text** (0.4 % of test), citing fact ids.
- **Ask by voice** in any browser (ElevenLabs speech-to-text) and an interactive "How it works" page.

### 4. Low inference cost

**$0.013 per 1,000 questions** in API fees: numeric answers make no paid calls; local compute adds ~$0.006. About 1/1,900 of the fair Sonnet baseline, at 0.04 s instead of ~16 s per answer.

### Built to be trusted

Security review and fixes on the public demo, a load test with many judges at once, an accessibility pass, 278 automated tests in CI.

A better model will still guess a number from pixels; ours reads it from the geometry and hands you the elements behind it. For Stoa: a takeoff engine cheap enough to run on every drawing, every revision. Models are plug-ins behind one evidence contract, and every human correction is a labelled example.

Built by Toivo and Rene at Junction 2026. Code: MIT; reproducible with the dataset + one command (`eval.py`). Drawings: Junction dataset, per-file licences, credited in the app.

---

## Technologies

Python, FastAPI, IfcOpenShell, ezdxf, PyMuPDF, Shapely, NumPy, Ultralytics YOLO11m, PyTorch, Hugging Face Transformers + PEFT (Qwen3-VL LoRA fine-tuning and live serving), vLLM, three.js (3D plans and BIM viewer), ElevenLabs Scribe (voice questions), Caddy, Playwright (demo recording, screenshots), pytest + GitHub Actions (tests and CI), Claude Sonnet 5.5 / Haiku 5.5 (baseline, LLM judge, free-text answers), Gemini 3.1 Pro and Nemotron 3.5 Super VL (baselines), Codex (cross-audit of the evaluation), Claude Code. Training: local RTX 4070 (detector) and cloud H100s (Verda) for the VLM; live VLM second opinion on a Verda GPU.

## Links

- Demo: TODO stable public URL
- Source: https://github.com/Zawaer/datum
- Video: TODO upload of `runs/video/` render (script: `docs/video.md`)
- Deck: `docs/deck/deck.pdf`

## Credits (shown on every drawing in the app, deck and video)

Swiss Dwellings v3.0.0 (Archilyse AG, CC BY 4.0) · CubiCasa5K (© 2019 CubiCasa, CC BY-NC-SA 4.0) · Molio Demo-hus
(buildingSMART Community Sample-Test-Files, CC BY 4.0) · BIM-Speed Warmond (TU Berlin, CC BY 4.0) · IFC-Bench v2
questions (S. Hellin, CC BY 4.0). Full per-file credits: `data/<source>/LICENSE.md` in the Junction dataset.
