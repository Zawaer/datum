# Blueprints That Talk

**Ask a construction drawing or a BIM model a question, in any language, and get the answer with its proof
drawn on the drawing.** Our Junction 2026 entry for Stoa's *Make Blueprints Talk* challenge.

On **all 25,420 questions of a held-out test split** we are right **88.2 %** of the time
[95 % CI 87.8–88.6], for **$0.014 per 1,000 questions** in API fees and 0.03 s per question.
The fair frontier comparison, **Claude Sonnet 5.5 given the drawing *and* its sibling CAD / IFC files** (the
same inputs our solvers read), gets **69.8 %** [60.9–78.4] at **$25.76 per 1,000**. That is +18 points at
about 1/1,800 of the cost. The evaluation was **audited independently** by a second AI lab's coding agent
(Codex, OpenAI), and every finding was re-checked: no leakage between dev and test, no test data in
training, tuning or calibration, no gold lookups at inference, and the headline recount reproduces.

A router sends every question to the cheapest method that can answer it **exactly**: CAD geometry for
vector plans, IfcOpenShell for BIM models, a small symbol detector for raster scans. Every answer comes with
its evidence. The doors it counted are numbered on the plan, the rooms it summed are outlined with their m²,
the walls it measured light up in 3D. You can check a number in seconds, and fix it with a click when it's
wrong.

![Counting doors on a Swiss apartment plan: 20 numbered boxes, each one a door read from the CAD layers](docs/deck/img/step-1.jpg)
<sub>Drawing: Swiss Dwellings v3.0.0, Archilyse AG, CC BY 4.0 (rendered by the Junction dataset authors).</sub>

- **Demo:** TODO public URL &nbsp;·&nbsp; **Video (2 min):** TODO link &nbsp;·&nbsp; **Deck:** [docs/deck/deck.pdf](docs/deck/deck.pdf)
- **Full results** (every table, figure and CI): [docs/RESULTS.md](docs/RESULTS.md) &nbsp;·&nbsp; **Costs:** [docs/COSTS.md](docs/COSTS.md)

## Results

Held-out test split of the full Junction dataset, **split by drawing**: every format of a drawing and every
language twin of a question stay on the same side, so nothing used in development is scored. Official
tolerance: counts exact, areas / lengths / volumes within 2 %. An abstention counts as wrong.

| system | accuracy [95 % CI] | API $ / 1,000 questions | s / question |
|---|---:|---:|---:|
| **Blueprints That Talk** (all 25,420 questions) | **88.2 %** [87.8–88.6] | **$0.014** | **0.03** |
| Claude Sonnet 5.5 + sibling CAD / IFC files¹ (fair comparison) | 69.8 % [60.9–78.4] | $25.76 | 15.6 |
| Claude Sonnet 5.5, drawing only¹ | 63.2 % [54.4–71.8] | $13.06 | 12.9 |
| Claude Haiku 5.5, drawing only¹ | 60.6 % [51.5–69.3] | $1.21 | 28.6 |
| Gemini 3.1 Pro, drawing only¹ | 64.2 % [55.9–72.3] | $52.47 | 31.4 |
| Nemotron 3.5 Super VL (open weights), drawing only¹ | TODO (run still finishing) | TODO | TODO |
| Most common answer per question template (no drawing) | 41.6 % [41.0–42.2] | $0 | 0 |

**By source (ours):** Swiss apartment plans 100.0 % (8,214 questions: counts 100.0 %, room areas 99.9 %),
IFC models 100 % on all 600 numeric questions (counts, areas, volumes, lengths), Finnish raster plans
(CubiCasa) 82.2 % (16,496 counts, YOLO detector), IFC-Bench free text 36.4 % (110 questions, LLM judge).
On the same 400 sampled questions, Sonnet with sibling files is right on 6 that we miss; we are right on 95
that it misses. Per-source tables for every system: [docs/RESULTS.md](docs/RESULTS.md) §2.

¹ **Frontier numbers come from a 400-question sample of the test split, stratified by source × type**
(~54 per cell), **re-weighted to the true test-split mix**, CI from a stratified bootstrap. Cost is the API list
price of the tokens used, re-weighted the same way. Calls that failed on a usage limit were re-run, so every baseline row is a real
answer. Gemini cannot
take a raw `.ifc` file inline, so the 61 sampled questions that come as an `.ifc` file (IFC-Bench text and some
IFC counts) abstain and count as wrong, by design; they are 0.5 % of the test mix after re-weighting.

Sources: ours = [`runs/router_full_test_v4.summary.md`](runs/router_full_test_v4.summary.md); frontier =
`runs/baseline_{sonnetfair,sonnet,haiku,gemini,nemotron}_full400.jsonl`; all tables rebuilt by
`analysis/run_all.sh` into [docs/RESULTS.md](docs/RESULTS.md) and `analysis/out/*.csv`.

## How we verify

Judges, reviewers and users should not have to take our word for any number. Three layers:

1. **Evidence contract, per answer.** Every solver returns `{answer, confidence, method, cost_usd,
   explanation, evidence[]}`. Evidence items are numbered boxes, measured room polygons with their m², text
   read from the drawing, or IFC GlobalIds with their own quantity, in page coordinates normalised to 0..1.
   **The values of the evidence items add up to the answer**, so a reviewer checks the arithmetic, not just
   a picture, and unticking an item or adding a missed one recomputes the answer on the spot. Spec:
   [`docs/EVIDENCE.md`](docs/EVIDENCE.md).
2. **Calibrated confidence, per answer.** The confidence is measured against the test split, not asserted
   ([RESULTS.md](docs/RESULTS.md) §3, fig. 3). Raster-plan answers at confidence ≥ 0.95 are right 98.2 % of the
   time. If the router answers only at confidence ≥ 0.5 and says "not sure" otherwise, it answers 86 % of all
   questions at 95.5 % accuracy, turning 2,027 wrong answers into honest abstentions. Known weak spot, stated
   in RESULTS.md: a symbol the detector misses entirely cannot lower its confidence.
3. **Independent audit, of the whole evaluation.** Codex (OpenAI) audited the repository read-only; a Claude
   agent re-verified every finding against the data. Confirmed: no split leakage (5,884 drawing groups, 0
   straddle dev and test), no test data in training, tuning or calibration (`train/cubicasa/make_yolo.py` and
   `train/vlm/build_dataset.py` drop test drawings before reading anything), no gold lookups at inference, and
   the headline recount reproduces (88.1 % rules-only, 88.2 % with the free-text judge; Sonnet 63.2 %).
   Fixed after the audit: the frontier baseline now also gets the sibling files (`claude@sonnet+twins`), and
   cached LLM answers report their real cost.

Free-text answers are scored by an LLM judge with a fixed rubric (`bp/judge.py`, validated against hand
labels) for **every** system alike, ours and the baselines.

## Costs

**$0.014 per 1,000 questions** in API fees, measured on all 25,420 test questions: numeric answers make no
paid calls at all; only the 110 free-text IFC questions call Claude Haiku. Local compute (CAD / IFC parsing on
CPU, the detector on one GPU, ~0.13 s per drawing) prices at about $0.005 per 1,000 questions at $0.50 per
GPU-hour. Building everything (frontier baselines, fine-tuning runs, development calls, demo hosting) cost
about $100 one-off. Per-answer and build costs, with every line item: [docs/COSTS.md](docs/COSTS.md)
(`.venv/bin/python analysis/costs.py` regenerates it).

## How it works

```
question + drawing ──► router (by source / file kind; type from multilingual keywords)
                         ├─ Swiss PDF/PNG ──► DXF twin: exact geometry by CAD layer        (bp/solvers/swiss.py)
                         ├─ IFC / plan rendered from IFC ──► IfcOpenShell tables          (bp/solvers/ifc.py)
                         ├─ raster plan (PNG/JPG) ──► YOLO11 symbol detector               (bp/solvers/cubicasa.py)
                         ├─ IFC free text ──► fact sheet with ids + cheap LLM that cites ids (bp/solvers/ifctext.py)
                         └─ anything else / uploads ──► generic grounded fallback           (bp/solvers/generic.py)
                                                       └► fine-tuned small VLM, boxes + count (bp/solvers/vlm.py, in progress)
answer + confidence + evidence ──► web app: numbered boxes / room polygons on the plan, elements lit in 3D
```

- **Router** ([`bp/router.py`](bp/router.py)). Picks the solver from the source and file kind; guesses the
  question type from keywords in English, Finnish, German, French, Italian, Danish, Estonian, Swedish, Dutch,
  Polish. A crashing or unsure solver abstains ("not sure") rather than guessing; a frontier fallback exists
  but is off by default.
- **Swiss Dwellings: CAD geometry** ([`bp/solvers/swiss.py`](bp/solvers/swiss.py), [`bp/swiss/parse.py`](bp/swiss/parse.py)).
  Questions are asked about the PDF; the dataset ships the same drawing as DXF, so we read doors, windows,
  sanitary fixtures, room outlines and apartment boundaries from the CAD layers with ezdxf and Shapely, and
  map the evidence back onto the PDF page through the room numbers both files share. No model call.
- **IFC models: IfcOpenShell** ([`bp/solvers/ifc.py`](bp/solvers/ifc.py), [`bp/ifc/`](bp/ifc/)). Counts, net
  areas, wall lengths and volumes from quantity sets and geometry, per storey. Questions about plan PDFs
  rendered from a model are answered from the model itself. Evidence = the GlobalId of every contributing
  element with its own value, highlighted in 3D (three.js) and on the plan.
- **Raster plans: detector** ([`bp/solvers/cubicasa.py`](bp/solvers/cubicasa.py), [`train/cubicasa/`](train/cubicasa/README.md)).
  One YOLO11 detector, trained on the public CubiCasa5K annotations of non-test drawings only, finds windows,
  doors, toilets, sinks, showers, bathtubs, sauna stoves and typed rooms. The question template picks the
  classes; each counted detection is a numbered box with its own score, and the confidence is calibrated on
  dev drawings. Trained on a local RTX 4070.
- **General grounded fallback: fine-tuned small VLM, in progress** ([`bp/solvers/vlm.py`](bp/solvers/vlm.py), [`train/vlm/`](train/vlm/)).
  Qwen3-VL-8B + LoRA, trained on cloud GPUs (Verda) on dev-split drawings only, answers with one box per
  counted item, so the count always equals the boxes. First run on a 1,000-question test sample: 70.0 % on
  Finnish raster counts and 58.8 % on Swiss counts ([`runs/vlm_q3vl8b_r2_test1000.summary.md`](runs/vlm_q3vl8b_r2_test1000.summary.md)),
  below the detector and the CAD path, so the router does not use it for those yet. Its job is drawings no
  specialised solver covers; a larger run is training.
- **Generic grounded fallback** ([`bp/solvers/generic.py`](bp/solvers/generic.py)). For uploads and other
  sources: the text layer of vector PDFs / DXF is split into segments with ids and an LLM must answer *by
  citing ids*, so sums are recomputed from what it cited; without a text layer, a vision model boxes every
  instance, tile by tile. On the 64 opening_design questions (no held-out split, so indicative) it answers
  92.2 % at $5.02 / 1,000 ([`generic_opening_haiku`](runs/generic_opening_haiku.summary.md)).
- **Free text about IFC** ([`bp/solvers/ifctext.py`](bp/solvers/ifctext.py), [`bp/judge.py`](bp/judge.py)).
  A fact sheet is extracted from the model, each line with an id that maps back to GlobalIds; rules answer the
  common question shapes and a cheap LLM answers the rest citing those ids. Free text is our weakest area
  (36.4 %), and we say so.

## Run it

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt fastapi uvicorn ultralytics torch playwright
playwright install chromium                     # only for screenshots / the video / the deck

# dataset (10 GB, non-commercial, not redistributed here)
mkdir -p data/full && cd data/full
curl -LO https://fwjydgxpttajiqpfmqtj.supabase.co/storage/v1/object/public/stoa-junction-2026/junction-dataset.zip
unzip -q junction-dataset.zip && cd ../..       # -> data/full/junction-dataset/questions.jsonl (or set BP_DATA)

# CubiCasa detector weights: see train/cubicasa/README.md (~1 h on an RTX 4070)

# demo app
.venv/bin/python -m uvicorn app.server:app --host 0.0.0.0 --port 3123    # http://localhost:3123
```

The app has a guided demo tour (`app/tour.json`), drawing upload (PDF, PNG, JPG, DXF, IFC), and a scoreboard
page that reads `runs/*.summary.md`. The numeric solvers need no API key.

## Reproduce every number

Each command writes `runs/<name>.jsonl` (one row per question: prediction, gold, correct, cost, latency,
evidence) and `runs/<name>.summary.md` (tables by type, source, source × type, language). The `--sample` is
deterministic (hash of path + question), and `--ids-from` re-runs exactly the questions of another run, so
every baseline answers the same 400 questions.

```bash
python eval.py --solver router --split test --jobs 8 --judge --name router_full_test_v4      # 88.2 %, all 25,420
python eval.py --solver claude@sonnet --split test --sample 400 --jobs 6 --name baseline_sonnet_full400
S=runs/baseline_sonnet_full400.jsonl
python eval.py --solver claude@sonnet+twins --split test --ids-from $S --jobs 6 --name baseline_sonnetfair_full400
python eval.py --solver claude@haiku  --split test --ids-from $S --jobs 6 --name baseline_haiku_full400
python eval.py --solver gemini        --split test --ids-from $S --jobs 6 --name baseline_gemini_full400
python eval.py --solver nemotron      --split test --ids-from $S --jobs 6 --name baseline_nemotron_full400
python eval.py --solver prior  --split test --name prior_full_test                                   # 41.6 %
BP_OURS_RUN=router_full_test_v4 bash analysis/run_all.sh   # judge baseline text answers, re-weighting, CIs,
                                                           # figures, docs/RESULTS.md, analysis/out/*.csv
.venv/bin/python analysis/costs.py                          # docs/COSTS.md
```

Per-solver checks: `--solver swiss`, `ifc`, `cubicasa`, `ifctext@combo --source ifc_bench --judge`, and
`vlm` (needs a served LoRA, see `train/vlm/README.md`). Rules and thresholds were tuned on the dev split only.

## Data, licences, credits

- **Code:** MIT licence (Junction submissions are MIT-licensed). Dependencies keep their own licences
  (notably Ultralytics YOLO, AGPL-3.0, installed from PyPI, not vendored).
- **Dataset:** the Junction 2026 construction drawings dataset by Stoa, **non-commercial use for the challenge,
  per-file licences** in `data/<source>/LICENSE.md`. It is not included in this repository. Drawings shown in
  this README, the deck and the video:
  - Swiss Dwellings v3.0.0, Matthias Standfest, Michael Franzen, Yvonne Schröder, Luis Gonzalez Medina, Yarilo
    Villanueva Hernandez, Jan Hendrik Buck, Yen-Ling Tan, Milena Niedzwiecka, Rachele Colmegna (Archilyse AG),
    [doi:10.5281/zenodo.7788422](https://doi.org/10.5281/zenodo.7788422), CC BY 4.0; plans rendered from the
    published geometry by the dataset authors.
  - CubiCasa5K, © 2019 CubiCasa; Kalervo, Ylioinas, Häikiö, Karhu, Kannala, "CubiCasa5K: A Dataset and an
    Improved Multi-Task Model for Floorplan Image Analysis", SCIA 2019, CC BY-NC-SA 4.0. The detector is trained
    on the public CubiCasa5K annotations ([Zenodo 2613548](https://zenodo.org/records/2613548)).
  - Molio Demo-hus, buildingSMART Community Sample-Test-Files contributors, CC BY 4.0.
  - BIM-Speed Warmond demo site, Garcia & Hartmann 2022, TU Berlin, doi:10.14279/depositonce-16441.2, CC BY 4.0.
  - IFC-Bench v2 questions, © 2025 Sylvain Hellin (TUM), CC BY 4.0.
- **Models:** Ultralytics YOLO11, Qwen3-VL (Apache-2.0), Claude Sonnet 5.5 / Haiku 5.5 (baselines, judge and
  free-text answers), Gemini 3.1 Pro and Nemotron 3.5 Super VL (baselines).

## Team

Toivo and Rene, Junction 2026 (Espoo, 13–15 Nov 2026). Built during the event with Claude Code.
