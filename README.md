# Blueprints That Talk

**Ask a construction drawing or a BIM model a question, in any language, and get the answer with its proof
drawn on the drawing.** Our Junction 2026 entry for Stoa's *Make Blueprints Talk* challenge.

On **all 25,420 questions of a held-out test split** (every question in every language, not a sample) we are right **89.5 %** of the time
[95 % CI 89.1–89.8], for **$0.013 per 1,000 questions** in API fees and 0.04 s per question.
The fair frontier comparison, **Claude Sonnet 5.5 given the drawing *and* its sibling CAD / IFC files** (the
same inputs our solvers read), gets **69.8 %** [60.9–78.4] at **$25.76 per 1,000**. That is +20 points at
about 1/1,900 of the cost. The evaluation was **audited independently** by a second AI lab's coding agent
(Codex, OpenAI), and every finding was re-checked: no leakage between dev and test, no test data in
training, tuning or calibration, no gold lookups at inference, and the headline recount reproduces.

A router sends every question to the cheapest method that can answer it **exactly**: CAD geometry for
vector plans, IfcOpenShell for BIM models, a small symbol detector for raster scans. Every answer comes with
its evidence. The doors it counted are numbered on the plan, the rooms it summed are outlined with their m²,
the walls it measured light up in 3D. You can check a number in seconds, and fix it with a click when it's
wrong. Four verification layers sit on top (below): **evidence that adds up**, **calibrated confidence**, an
**independent cross-check** by a second method, and **provenance** checks on every LLM-written number.

Stoa's brief asks for approaches next year's frontier models won't make obsolete: *"hybrids of frontier models
+ CV + 3D/geometry + small fine-tuned models"*. That is this system, piece by piece: CAD and IFC geometry, a
small CV detector, a fine-tuned 8B VLM as second opinion, and a frontier LLM only where free text needs it.

![Counting doors on a Swiss apartment plan: 20 numbered doors read from the CAD layers, "Very likely right", and a second, independent method that agrees](docs/deck/img/step-1.jpg)
<sub>Drawing: Swiss Dwellings v3.0.0, Archilyse AG, CC BY 4.0 (rendered by the Junction dataset authors).</sub>

- **Demo:** TODO public URL &nbsp;·&nbsp; **Video (2 min):** TODO link &nbsp;·&nbsp; **Deck:** [docs/deck/deck.pdf](docs/deck/deck.pdf)
- **Full results** (every table, figure and CI): [docs/RESULTS.md](docs/RESULTS.md) &nbsp;·&nbsp; **Costs:** [docs/COSTS.md](docs/COSTS.md)

## Results

Held-out test split of the full Junction dataset, **split by drawing**: every format of a drawing and every
language twin of a question stay on the same side, so nothing used in development is scored. Official
tolerance: counts exact, areas / lengths / volumes within 2 %. An abstention counts as wrong.

| system | accuracy [95 % CI] | API $ / 1,000 questions | s / question |
|---|---:|---:|---:|
| **Blueprints That Talk** (all 25,420 questions) | **89.5 %** [89.1–89.8] | **$0.013** | **0.04** |
| Claude Sonnet 5.5 + sibling CAD / IFC files¹ (fair comparison) | 69.8 % [60.9–78.4] | $25.76 | 15.7 |
| Claude Sonnet 5.5, drawing only¹ | 63.2 % [54.4–71.8] | $13.06 | 12.9 |
| Claude Haiku 5.5, drawing only¹ | 60.6 % [51.5–69.3] | $1.21 | 28.6 |
| Gemini 3.1 Pro, drawing only¹ | 64.2 % [55.9–72.3] | $52.47 | 31.4 |
| Nemotron 3.5 Super VL (open weights), drawing only¹ | 49.0 % [40.0–58.0] | $2.59 | 40.1 |
| Most common answer per question template (no drawing) | 41.6 % [41.0–42.2] | $0 | 0 |

**By source (ours):** Swiss apartment plans 99.95 % (8,210 of 8,214 questions: counts 99.96 %, room areas 99.92 %),
IFC models 100 % on all 600 numeric questions (counts, areas, volumes, lengths), Finnish raster plans
(CubiCasa) 84.2 % (16,496 counts, YOLO11m detector), IFC-Bench free text 38.2 % (110 questions, LLM judge;
our weakest area). On the same 400 sampled questions, Sonnet with sibling files is right on 3 that we miss; we
are right on 57 that it misses. Per-source tables for every system: [docs/RESULTS.md](docs/RESULTS.md) §2.

¹ **Frontier numbers come from a 400-question sample of the test split, stratified by source × type**
(~54 per cell, so each cell is ±~13 pp), **re-weighted to the true test-split mix**, CI from a stratified bootstrap. Cost is the API list
price of the tokens used, re-weighted the same way. Calls that failed on a usage limit were re-run, so every baseline row is a real
answer. Gemini cannot
take a raw `.ifc` file inline, so the 61 sampled questions that come as an `.ifc` file (IFC-Bench text and some
IFC counts) abstain and count as wrong, by design; they are 0.5 % of the test mix after re-weighting.

Sources: ours = [`runs/router_full_test_v6.summary.md`](runs/router_full_test_v6.summary.md) (was 88.2 % in v4; the
+1.3 points are the new CubiCasa detector, 82.2 % → 84.2 %; v6 adds the richer IFC fact sheet, free text 36.4 % → 38.2 %); frontier =
`runs/baseline_{sonnetfair,sonnet,haiku,gemini,nemotron}_full400.jsonl`; all tables rebuilt by
`analysis/run_all.sh` into [docs/RESULTS.md](docs/RESULTS.md) and `analysis/out/*.csv`.

## How we verify

Judges, reviewers and users should not have to take our word for any number. Four verification layers,
plus an audit of the whole evaluation and a robustness suite:

1. **Evidence that adds up.** Every solver returns `{answer, confidence, method, cost_usd, explanation,
   evidence[]}`. Evidence items are numbered boxes, measured room polygons with their m², text read from the
   drawing, or IFC GlobalIds with their own quantity, in page coordinates normalised to 0..1. **The values of the
   evidence items add up to the answer**, so a reviewer checks the arithmetic, not just a picture, and unticking
   an item or adding a missed one recomputes the answer on the spot ([`docs/EVIDENCE.md`](docs/EVIDENCE.md)).
   We measured that the boxes are right, not just the totals ([`docs/EVIDENCE_QUALITY.md`](docs/EVIDENCE_QUALITY.md)):
   against independent gold instances, CubiCasa boxes reach over 90 % precision and recall (box centres matched; 91 % / 86 % at
   IoU ≥ 0.5), and only about 2.5 % of correct counts are right by luck (a missed object and a false box cancelling out).
2. **Calibrated confidence.** Measured on the test split, not asserted ([RESULTS.md](docs/RESULTS.md) §3,
   fig. 3; the demo states it per answer from [`app/calibration.json`](app/calibration.json)). Raster-plan
   answers at confidence ≥ 0.95 are right 98.3 % of the time. If the router answers only at confidence ≥ 0.5 and
   says "not sure" otherwise, it answers 87.5 % of all questions at 95.4 % accuracy, turning 1,658 wrong answers
   into honest abstentions. Known weak spot: a symbol the detector misses entirely cannot lower its confidence.
3. **Independent cross-check.** A second, independent method re-derives the answer
   ([`runs/crosscheck_test.summary.md`](runs/crosscheck_test.summary.md), `bp/crosscheck.py`): Swiss answers are
   re-read from the PDF alone (text layer, fill polygons × printed scale, vector symbols), IFC answers from the
   plan sheet's SVG, CubiCasa answers by a separately trained second detector. Where they **agree, the answer was
   right on 99.98 % of Swiss and IFC test questions** (all but 2 of 8,184: one washbasin count, asked in two
   languages, where a symbol missing from the drawing fools both readings); the check caught a real Swiss error (an apartment area
   read as 86.72 m² from the DXF, 95.38 m² from the PDF, gold 95.36). On a conflict the answer is kept but its
   confidence is halved and both sets of marks are shown, never silently swapped. On CubiCasa the two detectors
   share training data, so that check is weaker (90.7 % right on agree vs 47.8 % on conflict, measured with the
   previous primary detector). So on raster plans the second opinion is now the fine-tuned Qwen3-VL-8B, a
   different model family: on all 16,496 CubiCasa test questions it agrees with the detector on 73.7 %, and
   there the detector is right **94.6 %** (55.1 % on conflict, where the VLM itself is right only 19.9 %, so it
   never overrides); with the confidence halved on conflict, the router answers 68.5 % of raster questions at
   96.5 % ([`runs/crosscheck_vlm_test.summary.md`](runs/crosscheck_vlm_test.summary.md)). The demo serves its
   precomputed answers and boxes.
4. **Provenance of LLM-written numbers.** Free-text answers are the least verifiable part, so
   `bp/provenance.py` traces every number and quoted name in an LLM answer to the fact lines it cited (sums,
   counts and group totals of cited lines included) and flags the answer when they don't match
   ([`docs/PROVENANCE.md`](docs/PROVENANCE.md)): 97 % of 4,328 claims on test trace; verified answers are
   judge-correct more often than the rest (63 % vs 52 % on dev, 28 % for unverified ones; 42 % vs 39 % on test,
   where only 1 is unverified), so the flag is shown, not hidden.

**Robustness** ([`docs/ROBUSTNESS.md`](docs/ROBUSTNESS.md)): the 12,654 language-twin pairs (same question in
English and Finnish / German / ...) agree 100 %; typed paraphrases go through a question normaliser (one cheap
Haiku call, only for questions no parser understands, constrained to names that exist in the drawing) and score
85.9 % vs 57.7 % before it, equal to the original wording (on a held-out set of 122 paraphrases written after
the code: 81.1 % vs 49.2 % before, originals 82.0 %); 50 of 50 must-abstain questions (unknown storeys,
nonsense) now abstain.

**Independent audit, of the whole evaluation.** Codex (OpenAI) audited the repository read-only; a Claude
agent re-verified every finding against the data. Confirmed: no split leakage (5,884 drawing groups, 0
straddle dev and test), no test data in training, tuning or calibration (`train/cubicasa/make_yolo.py` and
`train/vlm/build_dataset.py` drop test drawings before reading anything), no gold lookups at inference, and
the headline recount reproduces (88.1 % rules-only, 88.2 % with the free-text judge on v4; Sonnet 63.2 %).
Fixed after the audit: the frontier baseline now also gets the sibling files (`claude@sonnet+twins`), and
cached LLM answers report their real cost.

Free-text answers are scored by an LLM judge with a fixed rubric (`bp/judge.py`, validated against hand
labels) for **every** system alike, ours and the baselines.

## Costs

**$0.013 per 1,000 questions** in API fees, measured on all 25,420 test questions: numeric answers make no
paid calls at all; only the 110 free-text IFC questions call Claude Haiku. In the demo, typed questions that
no parser understands add one cached Haiku call for the normaliser (~$0.0003-0.003). Local compute (CAD / IFC parsing on
CPU, the detector on one GPU, ~0.13 s per drawing) prices at about $0.005 per 1,000 questions at $0.50 per
GPU-hour. Building everything (frontier baselines, fine-tuning runs, development calls, demo hosting) cost
about $165 one-off so far (the demo server, still running at the time of writing, is costed up to now). Per-answer and build costs, with every line item: [docs/COSTS.md](docs/COSTS.md)
(`.venv/bin/python analysis/costs.py` regenerates it).

## How it works

```
question + drawing ──► router (by source / file kind; type from multilingual keywords)
                         ├─ Swiss PDF/PNG ──► DXF twin: exact geometry by CAD layer        (bp/solvers/swiss.py)
                         ├─ IFC / plan rendered from IFC ──► IfcOpenShell tables          (bp/solvers/ifc.py)
                         ├─ raster plan (PNG/JPG) ──► YOLO11m symbol detector              (bp/solvers/cubicasa.py)
                         ├─ IFC free text ──► fact sheet with ids + cheap LLM that cites ids (bp/solvers/ifctext.py)
                         └─ anything else / uploads ──► generic grounded fallback           (bp/solvers/generic.py)
answer ──► second method re-derives it: agree / conflict / single                  (bp/crosscheck.py)
           (PDF re-read for Swiss, SVG sheet for IFC, 2nd detector + fine-tuned VLM for raster)
answer + confidence + evidence + cross-check ──► web app: numbered boxes / room polygons on the plan, elements lit in 3D
```

- **Router** ([`bp/router.py`](bp/router.py)). Picks the solver from the source and file kind; guesses the
  question type from keywords in English, Finnish, German, French, Italian, Danish, Estonian, Swedish, Dutch,
  Polish. Free wording that no parser understands ("how many WC bowls are there?") goes through the question
  normaliser ([`bp/normalize.py`](bp/normalize.py)): one Haiku call rewrites it into a supported template using
  only names that exist in this drawing, or declines; the app shows "read as: ...". A crashing or unsure solver abstains ("not sure") rather than guessing; a frontier fallback exists
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
  One YOLO11m detector (v4, 84.2 % on all 16,496 test counts; was 82.2 % with YOLO11s), trained on the public CubiCasa5K annotations of non-test drawings only, finds windows,
  doors, toilets, sinks, showers, bathtubs, sauna stoves and typed rooms. The question template picks the
  classes; each counted detection is a numbered box with its own score, and the confidence is calibrated on
  dev drawings. Trained on a local RTX 4070.
- **Fine-tuned small VLM, second opinion** ([`bp/solvers/vlm.py`](bp/solvers/vlm.py), [`train/vlm/`](train/vlm/)).
  Qwen3-VL-8B + LoRA, trained on cloud H100s (Verda) on dev-split drawings only, answers with one box per
  counted item, so the count always equals the boxes. Round 3 scores 73.0 % on a 1,000-question test sample
  (round 2: 64.4 %; [`runs/vlm_q3vl8b_r3c2200_test1000.summary.md`](runs/vlm_q3vl8b_r3c2200_test1000.summary.md)),
  below the detector and the CAD path, so it does not answer on its own: it is the cross-check's second
  opinion on raster plans. On all 16,496 CubiCasa test questions it scores 74.9 % alone (detector 84.2 %), agrees
  with the detector on 73.7 %, and where it agrees the detector is right 94.6 %
  ([`runs/vlm_r3_cubicasa_test_full.summary.md`](runs/vlm_r3_cubicasa_test_full.summary.md),
  [`runs/crosscheck_vlm_test.summary.md`](runs/crosscheck_vlm_test.summary.md)); $0.16 per 1,000 questions on
  one H100. A PaliGemma 2 fine-tune was weaker (52 % on dev) and is not shipped.
- **Generic grounded fallback** ([`bp/solvers/generic.py`](bp/solvers/generic.py)). For uploads and other
  sources: the text layer of vector PDFs / DXF is split into segments with ids and an LLM must answer *by
  citing ids*, so sums are recomputed from what it cited; without a text layer, a vision model boxes every
  instance, tile by tile. On the 64 opening_design questions (no held-out split, so indicative) it answers
  93.8 % at $4.85 / 1,000 ([`generic_opening_final`](runs/generic_opening_final.summary.md); an earlier run of the same setup scored 92.2 %).
- **Free text about IFC** ([`bp/solvers/ifctext.py`](bp/solvers/ifctext.py), [`bp/judge.py`](bp/judge.py)).
  A fact sheet is extracted from the model, each line with an id that maps back to GlobalIds; rules answer the
  common question shapes and a cheap LLM answers the rest citing those ids. Free text is our weakest area
  (38.2 %), and we say so.

## Run it

Tested with Python 3.11 on Linux with an NVIDIA GPU (the detector also runs on CPU, slower). Run everything
from the repository root.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt                 # ~8 min, ~6.5 GB (torch with CUDA from PyPI)
playwright install chromium                     # only for screenshots / the video / the deck

# dataset (10 GB, non-commercial, not redistributed here)
mkdir -p data/full && cd data/full
curl -LO https://fwjydgxpttajiqpfmqtj.supabase.co/storage/v1/object/public/stoa-junction-2026/junction-dataset.zip
unzip -q junction-dataset.zip && cd ../..       # -> data/full/junction-dataset/questions.jsonl (or set BP_DATA)

# CubiCasa detector weights: not in git. Train them with train/cubicasa/README.md (5.5 GB download, 1-2 h per
# run on an RTX 4070; ~5 GPU-h across all our iterations) -> cache/cubicasa/weights/{best.pt,thresholds.json,calib.json}

# demo app
.venv/bin/python -m uvicorn app.server:app --host 0.0.0.0 --port 3123    # http://localhost:3123
```

**Without the detector weights**, Swiss and IFC questions work fully, but every raster-plan (CubiCasa)
question abstains with "cubicasa solver failed: FileNotFoundError", which is 16,496 of the 25,420 test
questions. Point `CUBICASA_WEIGHTS` at a `best.pt` if yours is elsewhere.

The app has a guided demo tour (`app/tour.json`), drawing upload (PDF, PNG, JPG, DXF, IFC), and a scoreboard
page that reads `runs/*.summary.md`.

**API keys.** Every numeric answer (counts, areas, lengths, volumes) needs no key and no network. Only these
call a model:

| feature | needs |
|---|---|
| IFC free-text answers, the typed-question normaliser, the `--judge` scorer, `claude@*` baselines | the Claude Code CLI (`npm install -g @anthropic-ai/claude-code`) on `PATH` (`claude`, logged in or with `ANTHROPIC_API_KEY`), or `CLAUDE_CLI=/path/to/claude` |
| `gemini` baseline | `GEMINI_API_KEY` |
| `nemotron` baseline | `NVIDIA_API_KEY` |

Without the CLI nothing crashes: free-text IFC questions fall back to the rule-based fact-sheet answer
(after ~12 s of retries per question), and a typed question no parser understands gets "question not
understood" plus the labels the drawing does have.

## Reproduce every number

Each command writes `runs/<name>.jsonl` (one row per question: prediction, gold, correct, cost, latency,
evidence) and `runs/<name>.summary.md` (tables by type, source, source × type, language). The `--sample` is
deterministic (hash of path + question), and `--ids-from` re-runs exactly the questions of another run, so
every baseline answers the same 400 questions.

**Quick check without keys** (~6 min on an RTX 4070 + 8 CPU threads, $0):

```bash
python eval.py --solver router --split test --jobs 8 --name router_check     # all 25,420, no --judge
```

This scores free text with a token-F1 proxy instead of the LLM judge, so expect 89.5 % (ifc_bench text
34.5 % instead of 38.2 %; every other cell as in [`runs/router_full_test_v6.summary.md`](runs/router_full_test_v6.summary.md)).
Do not pass `--judge` without the Claude CLI: a failed judge call scores the answer as wrong. A
`--sample N` run is stratified by source × type, not weighted to the test mix, so compare its
per-source rows, not its "ALL" row, with the headline.

The full set (the baselines need the keys above):

```bash
python eval.py --solver router --split test --jobs 8 --judge --name router_full_test_v6      # 89.5 %, all 25,420
python eval.py --solver claude@sonnet --split test --sample 400 --jobs 6 --name baseline_sonnet_full400
S=runs/baseline_sonnet_full400.jsonl
python eval.py --solver claude@sonnet+twins --split test --ids-from $S --jobs 6 --name baseline_sonnetfair_full400
python eval.py --solver claude@haiku  --split test --ids-from $S --jobs 6 --name baseline_haiku_full400
python eval.py --solver gemini        --split test --ids-from $S --jobs 6 --name baseline_gemini_full400
python eval.py --solver nemotron      --split test --ids-from $S --jobs 6 --name baseline_nemotron_full400
python eval.py --solver prior  --split test --name prior_full_test                                   # 41.6 %
python eval.py --solver router --split test --source swiss_dwellings --source ifc_models --source cubicasa5k \
  --crosscheck --name crosscheck_test                                                         # cross-check
BP_OURS_RUN=router_full_test_v6 bash analysis/run_all.sh   # judge baseline text answers, re-weighting, CIs,
                                                           # figures, docs/RESULTS.md, analysis/out/*.csv
.venv/bin/python analysis/costs.py                          # docs/COSTS.md
```

`analysis/run_all.sh` and `analysis/costs.py` read the per-question `runs/*.jsonl` logs and the spend logs
under `cache/`, which are not in git (only the `runs/*.summary.md` tables are). Run them after the eval
commands above, not on a fresh clone: there, `costs.py` would rewrite `docs/COSTS.md` with $0 rows.

Per-solver checks: `--solver swiss`, `ifc`, `cubicasa`, `ifctext@combo --source ifc_bench --judge`, and
`vlm` (needs a served LoRA, see `train/vlm/README.md`). Rules and thresholds were tuned on the dev split only.

## Data, licences, credits

- **Code:** MIT licence, see [LICENSE](LICENSE) (Junction submissions are MIT-licensed). Dependencies keep
  their own licences (notably Ultralytics YOLO, AGPL-3.0, installed from PyPI, not vendored); see
  [THIRD_PARTY.md](THIRD_PARTY.md). Screenshots that show dataset drawings carry the drawing's licence, not MIT.
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
