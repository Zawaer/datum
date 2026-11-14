# Datum: architecture for the judges

How a question becomes an answer, which model does what, what each costs and how accurate it is. Every number
is from a run log in `runs/` (named next to it) or from [COSTS.md](COSTS.md); full tables in
[RESULTS.md](RESULTS.md). The demo, video and pitch leave this out on purpose: they are about what a site
engineer gets. This page is about how it is built.

## The flow in one paragraph

```
upload ─► prepare ─────────────────────► router ─────────────► solver ──────────► checks ────────► evidence contract ─► UI
          file kind, page check,          file kind, sheet       one per question   cross-check,     answer + confidence +
          sheet type, vector text         type, question         (table below)      calibration,     marks on the user's own
          or OCR, rotation, phone-photo   keywords (10 langs);                      number guard,    drawing, replay, 3D
          flattening, memory gate         non-English upload                         text locator,
                                          questions translated                       provenance
```

**Prepare** (`app/server.py: _prepare`, once per file). The file kind is read from the file itself: IFC, DXF,
vector PDF (has a text layer), raster PDF, or image (HEIC, TIFF, WebP, SVG and others are converted first). A
phone photo of a printed sheet is flattened (`bp/generic/rectify.py`, classical CV). A vector PDF's words and
linework come from PyMuPDF; a drawing set's sheet ids and titles are read from the title blocks
(`bp/generic/sheetindex.py`, ~10 ms a page, no model). Two small Claude Haiku calls on a downscaled view decide
whether the upload is a drawing at all, whether it is sideways, whether it looks like a residential plan
(`bp/generic/sheets.py`), and which sheet type it is: floor, slab, piping or other (`bp/sheets/__init__.py:
classify`). On a scan, Tesseract OCR starts in the background. Heavy image work queues behind a process-wide
memory budget (`bp/memgate.py`) so a burst of large uploads waits instead of crashing the server.

**Route** (`bp/router.py`). Deterministic rules, no model: the file kind and sheet type pick the solver, and
keywords in ten languages pick the question type (count, area, length, volume, text). An upload question in
Finnish, German or Swedish is first translated to English by one cached Haiku call (`bp/intent.py`); numbers,
units, tags and sheet ids must survive unchanged or the translation is dropped. A two-part question is split and
each part routed on its own. Free wording no template covers is rewritten to a supported template
(`bp/normalize.py`). When a specialist abstains or is below confidence 0.3, the general reader gets the question
and the more confident answer is kept.

**Verify.** After the solver, on every answer: the **cross-check** re-derives the number by a second method that
reads something else (`bp/crosscheck.py`); on a conflict the confidence is halved, never silently switched. The
**confidence** is calibrated on dev drawings and turned into "answers like this were right N % of the time on M
test questions" (`app/calibration.py`). The **number guard** catches a thousands separator read as a decimal point
(`bp/numguard.py`). The **text locator** checks that every box citing printed text sits on that text, moves it there
or drops it (`bp/generic/locate.py`). **Provenance** traces every number in an LLM-written answer to the fact lines
it cited (`bp/provenance.py`; 97 % of 4,328 claims on test, [PROVENANCE.md](PROVENANCE.md)).

**Evidence contract** ([EVIDENCE.md](EVIDENCE.md)). Every solver returns the same shape: answer, confidence,
method, cost, explanation, and evidence items (boxes, polygons with their m², measured lines, table cells, IFC
GlobalIds) whose values add up to the answer. The UI only draws this contract, so a new model is a plug-in.

## Every model and engine

"Per question" is the marginal API cost at list price. Local compute for the whole test set prices at about
$0.009 per 1,000 questions ([COSTS.md](COSTS.md)).

| component | what it is | when it runs | $ per question | measured accuracy (source) |
|---|---|---|---|---|
| **IfcOpenShell** | IFC parser; our rules over quantities, types, storeys | IFC models: counts, areas, volumes, lengths | $0 | 100 % on 600 test questions (`router_full_test_v8`) |
| **ezdxf + Shapely** | DXF layers and geometry | Swiss plans (the DXF twin of the asked PDF): counts, room areas | $0 | 99.96 % counts (5,580), 99.92 % areas (2,634) (`router_full_test_v8`) |
| **PyMuPDF** | vector words and linework of a PDF | every vector PDF upload; the Swiss second method | $0 | feeds the sheet specialists (below) |
| **YOLO11m v4**, trained by us | symbol and room detector, 15 classes; trained on CubiCasa5K (test drawings removed before extraction) on a local RTX 4070, ~5 GPU-h | raster residential plans (CubiCasa); door / window counts on low-res floor-plan uploads | $0 (local, ~0.19 s per drawing with flip TTA) | 85.1 % alone on 16,496 test questions (`cubicasa_test_fliptta`) |
| **YOLO11s v3** | our earlier detector | second opinion on a CubiCasa question only when the VLM has no answer | $0 | used on 75 of 16,496 (`crosscheck_vlm_test_v8`) |
| **Qwen3-VL-8B + our LoRA** (r3, checkpoint-2200) | vision-language model fine-tuned to count with one box per item, on 2× Verda H100s (14.9 GPU-h, $77.33) | CubiCasa plans: second opinion on every count, and arbiter (below) | $0.00016 (one H100, 16,496 questions in 31 min) | 74.9 % alone on 16,496 (`vlm_r3_cubicasa_test_full`); when it agrees with the detector (73.9 %), 94.9 % right (`crosscheck_vlm_test_v8`) |
| **Claude Haiku 5.5** (API) | small frontier LLM, text and vision | IFC free text; upload page check and sheet type; question translation; tile reads of tags, room names, slab notes and table rows OCR could not read; text Q&A over a sheet's read lines | ~$0.002 per upload check; free text $0.34 for 110 questions (~$0.003 each); sheet questions $0.003 for 41 on vector PDFs, $0.09 to $0.20 for 41 on images and scans | IFC free text 38.2 % (110, LLM judge; `router_full_test_v8`) |
| **Tesseract OCR** | local OCR | scans and images of sheets: tags, tables, room labels; checking text-evidence boxes | $0 | inside the sheet results below |
| **Sheet specialists** (`bp/sheets/`) | plain code over words and lines, OpenCV for walls, door swings, glazing, zones, double-line pipes | uploads classified as floor, slab or piping plans | $0 on vector PDFs; Haiku only for what OCR misses | 41 questions on Stoa's 4 example sheets: vector PDF 40, full-res PNG 37, 2,500 px PNG 38, 2,000 px JPG 31, scanned PDF 37, rough scan 33 (`stoa_examples_v9c_forms`) |
| **Generic reader** (`bp/solvers/generic.py`) | Haiku answers by citing text-segment ids, code recomputes sums; Haiku boxes symbols tile by tile on rasters | anything no specialist claims, and specialist abstentions | ~$0.003 to $0.01 | 1 of 41 example-sheet questions lands here per image form |
| **ElevenLabs Scribe / TTS** | speech to text, text to speech | voice questions and spoken answers only | per use | not in the answer path |

Not in the product: Claude Sonnet 5.5, Gemini 3.1 Pro and Nemotron 3.5 Super VL are baselines only; Haiku is also
the LLM judge that scores free text for every system in the evaluation. The router supports a frontier fallback
below confidence 0.5, off in every run and in the demo.

## How many language models, and how they are weighted

**Two** language models are in the answer path: **Claude Haiku 5.5** (API) and **our fine-tuned Qwen3-VL-8B**.
Everything else is geometry, classical CV, OCR or our own YOLO detector.

**Nothing is averaged or voted.** Each question has exactly one primary answerer, picked by the routing rules
above. A second method can only (a) halve the confidence on a conflict, which the 0.5 threshold usually turns into
"not sure", or (b) in one narrow, dev-fitted case replace the detector's count (the arbiter, next section).
Haiku never measures: on the numeric paths it chooses what to read and cites line or segment ids, and our code
reads the value and does the arithmetic.

**The cost logic** is the routing rule read the other way: use the cheapest source that is exact. A vector PDF, a
DXF or an IFC model is read directly without any AI, so the answer costs $0. A scan needs OCR, which is local and
$0. Only text OCR cannot read goes to Haiku, as a crop. On the 25,420 test questions: CAD / IFC geometry 34.7 %,
our detector 64.9 %, Haiku 0.4 % (the 110 free-text questions), so 99.6 % of questions make no paid call and the
total is $0.013 per 1,000.

## Where the fine-tuned model runs, and the v8 arbiter

The fine-tuned Qwen3-VL-8B runs **only on CubiCasa-style raster residential plans, for counts**: dataset
questions, and uploads that the page check marks as a single-page residential plan asked to count windows, doors,
toilets, sinks, showers / baths or saunas.

- **Second opinion** (`bp/crosscheck.py: vlm_answer`): its count is compared with the detector's. It is a
  different model family reading the whole image, so its errors correlate less than a second YOLO's. Agree: 73.9 %
  of questions, 94.9 % right. Conflict: confidence halved, both sets of boxes shown. On a conflict the detector is
  right 60.8 % and the VLM 14.2 %, so the VLM never takes over wholesale.
- **Arbiter** (new in v8, `bp/solvers/cubicasa.py: arbitrate`): a per-template rule fit on dev-validation drawings
  (`train/cubicasa/arbiter_dev.py`, 2-fold CV on dev, swept on 2× Verda H100s for $30.80) takes the VLM's count only
  when they disagree, the detector's confidence is below a template threshold and the VLM's above one. A switched
  answer gets the Wilson 95 % lower bound of that template's dev precision as its confidence (cap 0.97). On test it
  switched 387 of 16,496 answers; CubiCasa accuracy 85.1 % → 86.1 % (+1.05 pp, 95 % CI +0.75 to +1.38 over
  drawings, `cubicasa_test_vlmarb`), whole system 90.0 % → 90.7 %. A switched answer is then cross-checked by the
  v3 detector instead.
- **Serving.** Precomputed for every test question and every demo drawing (`runs/vlm_r3_cubicasa_test_full.jsonl`,
  `cache/vlm/demo_secondopinion.jsonl`), so the public demo needs no GPU. **Live** for new uploads: the same adapter
  served on a Verda RTX PRO 6000 (transformers + PEFT behind Caddy TLS, `deploy/vlm/serve.sh`, `bp/vlm/live.py`, 20 s
  limit), started on demand when a residential plan is uploaded and stopped when idle. It ran 2.1 h on Saturday
  ($5.94) and the machine has since been deleted; without it, an upload simply gets no VLM opinion.

## Cost and latency

| path | API $ per 1,000 questions | latency per question |
|---|---|---|
| whole router, 25,420 test questions | $0.013 (+ ~$0.009 local compute) | 0.06 s mean |
| Swiss DXF geometry | $0 | 0.001 s median, 0.06 s cold per drawing |
| CubiCasa detector (+ arbiter lookup) | $0 | 0.011 s median, 0.18 s cold per drawing |
| IFC geometry | $0 | 0.03 s median, 11 s worst (large model) |
| VLM second opinion, if served | $0.16 | 1.2 s on an H100 |
| uploaded sheets, Stoa examples | $0.07 (vector PDF) to $5 (rough scan) | 0.4 to 2.9 s median, 53 s worst (first question on a rough scan) |
| Claude Sonnet 5.5 + same files (baseline) | $25.76 | 15.7 s |

Sources: RESULTS.md sections 1 and 6, `vlm_r3_cubicasa_test_full`, `stoa_examples_v9_pdf`,
`stoa_examples_v9c_*`. Sheet latencies exclude the one-off upload preparation (page check, classification,
background OCR). The one-off build cost was $217.12, of which Verda $115.01 ([COSTS.md](COSTS.md)).

## The marks are the user's own drawing

Nothing is generated. Every box, outline, line and table-cell mark is drawn on the user's own uploaded drawing, at
the coordinates where the value was read or measured: the detector's box, the room polygon traced from the walls
or CAD layers, the PDF word's bounding box, the IFC element by its GlobalId. Text marks are checked against the
words printed under them and dropped if they do not land on them. The 3D view lays the same drawing on the floor
and extrudes walls read from it (CAD layers, the IFC model's own geometry, or the dark wall strokes of a raster);
door leaves and glass are generic shapes placed in the gaps found in those walls.

## IP and licences

- **Our code:** MIT ([LICENSE](../LICENSE)), owned by the team.
- **Detector weights:** trained on CubiCasa5K, CC BY-NC-SA 4.0, so the shipped weights are non-commercial. For
  production we would retrain on Stoa's or the customer's own drawings: same pipeline (`train/cubicasa/`), only the
  training data changes. Every user correction is stored as a labelled example for that.
- **Fine-tuned VLM:** Qwen3-VL-8B-Instruct is Apache-2.0; our LoRA adapter is ours. It was also trained on
  CubiCasa5K and Swiss Dwellings dev drawings, so the CubiCasa non-commercial terms apply to it as well until
  retrained.
- **Data:** Swiss Dwellings, Molio Demo-hus, BIM-Speed Warmond and IFC-Bench questions are CC BY 4.0; the Junction
  dataset is non-commercial with per-file licences (Credits in [submission.md](submission.md)). Stoa's example
  sheets are public US government and UK OGL drawings, not stored in the repository.
- **Claude Haiku** is used through Anthropic's API; API inputs are not used for training.
- **Uploads** stay on our server (`cache/uploads/`). What leaves it: one downscaled view per upload for the
  drawing / sheet-type check, and crops of a raster sheet where OCR cannot read the text, both to Claude Haiku.
  A vector PDF's text never needs a crop. There is no automatic expiry of uploads yet.

## Limits

- **Raster counting is the weak core:** 86.1 % on CubiCasa plans; windows 53 % exact (eight-plus thin symbols,
  mostly under-counted). At confidence ≥ 0.5 it answers 82 % at 93.5 %.
- **Free text about IFC models:** 38.2 % (LLM judge, 110 questions); rules cover common shapes, the rest says
  "not available".
- **Uploaded sheets are measured on few sheets:** 41 example questions, 11 sibling-sheet questions (9 right). On a
  harder set of 40 engineer-style questions (13 sheets, 4 languages, 5 must-decline) the last full run got 27/40 on
  vector PDFs and 21 to 25/40 on images (`judge_1725`), before the latest scan fixes; not re-run since.
- **Low resolution:** the school plan at 2,000 px gives 1 of 8; such sheets answer totals only and say why.
- **Unseen slab plans:** areas on the imperial S-100A came out 23 to 41 % low, flagged unsure.
- **The detector licence** (above) and the CubiCasa domain: the detector and VLM are trained on Finnish
  residential plans; other plan styles go to the sheet specialists or the generic reader.
- **The live VLM** depends on a GPU being up; the CPU-only demo falls back to precomputed answers.
