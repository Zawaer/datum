# Submission texts (numbers from docs/RESULTS.md, docs/COSTS.md, runs/*.summary.md)

Every number below comes from a run log (`runs/*.jsonl`, rebuilt into `docs/RESULTS.md` by
`BP_OURS_RUN=router_full_test_v8 bash analysis/run_all.sh`), from `docs/COSTS.md`, or from the verification
reports (`runs/stoa_examples_v8_*.summary.md` for the construction sheets, `runs/crosscheck_test.summary.md`, `runs/crosscheck_vlm_test_v7.summary.md`, `runs/cubicasa_test_vlmarb.summary.md`, `docs/EVIDENCE_QUALITY.md`, `docs/ROBUSTNESS.md`, `docs/PROVENANCE.md`).
TODO markers remain only for the demo / video links.

## Project name (≤ 30 chars)

Datum

_(5 characters. On a drawing, the datum is the fixed reference every measurement is taken from; every Datum answer traces back to the drawing. Tagline where there is room: "blueprints that talk".)_

## Punchline (≤ 200 chars)

Datum: ask a drawing or BIM model anything, in any language. 90.7 % right on 25k held-out questions vs 69.8 % for a frontier model given the same files, every answer shown on the drawing.

_(187 characters)_

## Short version (~600 chars, for quick paste)

Datum answers questions about construction drawings and BIM models, typed or spoken, and shows the proof on the drawing: counted doors numbered, rooms outlined with their m², table cells and pipe runs marked, and a short replay of how the answer was worked out. Uploaded floor, slab and piping sheets go to specialists that read the sheet's own text and lines: 40/41 right on Stoa's example sheets as vector PDFs, weaker on low-res scans. On 25,420 held-out test questions: 90.7 % at $0.013 per 1,000, vs 69.8 % for Claude Sonnet 5.5 with the same files at $25.76. 493 automated tests.

_(585 characters)_

## Description (≤ 5000 chars, markdown)

_Character count of the block between the rules below: 4,265 (limit 5,000)._

---

**Quantity takeoff is slow by hand, and AI is not trusted with it.** A general model that gets a room area wrong looks exactly as confident as when it is right. **Datum** answers questions about drawings and BIM models (six languages tested, typed or spoken) and shows the proof: ask "how many doors?" and the plan rises into 3D with the counted doors lit and numbered.

**Outcome:** 90.7 % [90.4–91.1] on all 25,420 held-out test questions at **$0.013 per 1,000**, vs 69.8 % for Claude Sonnet 5.5 given the same files at $25.76.

### 1. Accuracy

Split by whole drawing (20 % test; formats and language twins stay together). Counts exact, measures within 2 %, abstentions count as wrong.

| | accuracy [95 % CI] | $ / 1,000 q |
|---|---|---|
| **Ours, all 25,420 questions** | **90.7 %** [90.4–91.1] | **$0.013** |
| Claude Sonnet 5.5 + CAD/IFC files* | 69.8 % [60.9–78.4] | $25.76 |
| Gemini 3.1 Pro, drawing only* | 64.2 % | $52.47 |
| Claude Sonnet 5.5, drawing only* | 63.2 % | $13.06 |
| Claude Haiku 5.5, drawing only* | 60.6 % | $1.21 |
| Nemotron 3.5 Super VL (open)* | 49.0 % | $2.59 |

By source: Swiss plans 99.95 % (8,214), IFC numeric 100 % (600), Finnish raster plans 86.1 % (16,496), IFC free text 38.2 % (110, LLM judge; our weak spot). \*400-question stratified sample, re-weighted.

A second AI agent (Codex) audited the evaluation: no leakage, no test data in training or tuning; the recount reproduces. Language twins agree on 12,582 of 12,654 pairs (99.4 %); 49/50 must-abstain questions abstain.

### 2. Complex sheets, uploaded

For final judging, Stoa uploads unseen complex sheets. Each upload is classified once; questions go to a specialist that reads the sheet's own text (exact on vector PDFs, OCR on scans) and linework:

- **Floor plans:** doors and windows (swing arcs, glazing strips, checked against the door schedule), room areas, baseboard metres, schedule tables and colour zones.
- **Slab plans:** area by type (thickness + bars), reinforcement, trenches, sumps, joint panels.
- **Piping plans:** tag counts, pipe sizes, notes, referenced sheets, run lengths.

On Stoa's four example sheets (41 questions): vector PDF 40/41, full-res PNG 37/41, 2,000 px JPG 33/41, 2,500 px PNG 26/41, scanned PDF 27/41. Before the specialists, the generic reader got 22 of the original 34 on the PDFs (now 33). On sibling sheets we never tuned on: 9/11. Weak: low-res school plans (1–2 of 8 below full resolution; coarse sheets give totals only and say why), the slab plan from 2,500 px or a scan (6–7 of 12) and small slabs from low-res images (on the held-out S-100A/B slab plans the PDF areas land within 1–4 % of hand measurements; from 2,000 px JPGs the 6" slabs come out ~40 % low, flagged low confidence).

### 3. Visualising reasoning

- **Proof on the drawing:** numbered boxes, rooms with their m², table cells outlined, pipe runs with their length, IFC elements lit in 3D. Untick an item and the total updates.
- **Replay:** the answer works itself out on the drawing in 2–4 s, from scale to total.
- **Calibrated confidence:** answering only at ≥ 0.5 keeps 88.8 % of questions at 95.6 %.
- **Cross-check:** a second method re-derives 98 % of numeric answers; where they agree, Swiss and IFC answers are right 99.98 %.
- **Provenance:** every number in an LLM-written answer is traced to the facts it cites, or flagged.

### 4. Creativity

A router sends each question to the cheapest method that answers it **exactly**: CAD layers, IfcOpenShell, sheet specialists, a YOLO11m detector we trained, our fine-tuned Qwen3-VL 8B as second opinion and narrow arbiter, Claude Haiku 5.5 only for free text and unread sheet text. Ask by voice (ElevenLabs). Uploaded floor plans rise into 3D too.

### 5. Low inference cost

**$0.013 per 1,000 questions** on the test set: numeric answers make no paid calls. On the example sheets, $0.003 for all 41 questions on vector PDFs, $0.09–0.18 on images (OCR is local; Claude Haiku reads only what OCR cannot).

### Built to be trusted

Security review, load test, accessibility pass, 493 automated tests in CI. Models are plug-ins behind one evidence contract; every correction is a labelled example.

Built by Toivo and Rene at Junction 2026. Code: MIT; reproducible with one command (`eval.py`).

---

## Technologies

Python, FastAPI, IfcOpenShell, ezdxf, PyMuPDF (vector text and linework of PDF sheets), Shapely, NumPy, OpenCV and Tesseract OCR (construction sheets), Ultralytics YOLO11m, PyTorch, Hugging Face Transformers + PEFT (Qwen3-VL LoRA fine-tuning and live serving), vLLM, three.js (3D plans and BIM viewer), ElevenLabs Scribe (voice questions), Caddy, Playwright (demo recording, screenshots), pytest + GitHub Actions (tests and CI), Claude Sonnet 5.5 / Haiku 5.5 (baseline, LLM judge, free-text answers), Gemini 3.1 Pro and Nemotron 3.5 Super VL (baselines), Codex (cross-audit of the evaluation), Claude Code. Training: local RTX 4070 (detector) and cloud H100s (Verda) for the VLM; live VLM second opinion on a Verda GPU.

## Links

- Demo: TODO stable public URL
- Source: https://github.com/Zawaer/datum
- Video: TODO upload of `runs/video/` render (script: `docs/video.md`)
- Deck: `docs/deck/deck.pdf`

## Credits (shown on every drawing in the app, deck and video)

Swiss Dwellings v3.0.0 (Archilyse AG, CC BY 4.0) · CubiCasa5K (© 2019 CubiCasa, CC BY-NC-SA 4.0) · Molio Demo-hus
(buildingSMART Community Sample-Test-Files, CC BY 4.0) · BIM-Speed Warmond (TU Berlin, CC BY 4.0) · IFC-Bench v2
questions (S. Hellin, CC BY 4.0). Full per-file credits: `data/<source>/LICENSE.md` in the Junction dataset.
