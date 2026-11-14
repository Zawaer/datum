# Evidence quality: do the boxes point at the right things?

A count answer from Stoa comes with numbered boxes on the drawing ("door 1 ... door 8"). Calling that
*verifiable* only means something if the boxes are right, so we measured them. For every test-split count
question that comes with boxes, we matched the boxes one-to-one to **independent gold instances**
of the asked class and report:

- **precision**: share of our boxes that land on a real instance of the asked class;
- **recall**: share of the gold instances that got a box;
- **count right AND boxes right**: the count is correct *and* every box matched and every instance is boxed.
  The last column, "of right counts, boxes right", answers: when the number is right, is it right for the
  right reason?

Three match rules: **IoU ≥ 0.5**; **centre**: our box's centre lies inside the gold box; **either-centre**:
either box's centre lies inside the other. The third rule exists for gold boxes that are thin or cover only
part of a symbol (see the notes below). Matching is greedy and one-to-one, so two boxes on one
door count as one hit and one false positive.

Reproduce: `.venv/bin/python analysis/evidence_scoring.py` (about 5 s) writes
`analysis/out/evidence_hitrate.csv` with every group, subset and rule, and per-question rows to
`runs/evidence_hitrate_rows.jsonl`. Input: `runs/router_full_test_v4.jsonl`, all 25,420 test answers
with their evidence, as logged by `eval.py`.

## Where the gold comes from

| source | gold instances | independent of our solver? |
|---|---|---|
| cubicasa5k (PNG) | the CubiCasa5k SVG annotation of the drawing: windows, doors with a leaf, toilets, sinks, showers and bathtubs, sauna rooms and the stoves outside them, typed rooms, storeys. We count them with the definitions recovered on dev drawings by `train/cubicasa/check_gold.py` (`bp/cubicasa/classes.py`) | yes. The solver only sees the PNG. The **test** drawings' annotations were extracted for this evaluation only (`analysis/extract_eval_gold.py` → `cache/eval_gold/`, 958 drawings); training and tuning code never reads that folder, and `train/cubicasa/extract_cc5k.py` still skips every test drawing |
| ifc_models (plan PDFs) | the IfcConvert SVG twin of the sheet: every `<g class="… IfcDoor" data-guid=…>` of the asked class | partly. Our 2D boxes are drawn from the same SVG, so **precision is 100 % by construction** whenever we box something. The test is whether we picked the right class on the right storey (precision) and whether every element on the sheet got a box (recall) |
| swiss_dwellings (PDF) | an **independent PDF-vector extraction** (PyMuPDF on the PDF, never the DXF our solver reads). Doors: the grey 0.37 pt swing arcs, one per door. Windows: groups of parallel, equal-length black 0.37 pt glazing lines | yes. The door extraction reproduces the official count on all 386 test door questions (and on 115/115 dev questions we checked first). The window extraction reproduces it on only 203/386, so windows are scored on those 203 ("gold-consistent"). Toilets, washbasins, bathtubs, showers and apartments have no reliable PDF-only extraction and are **not scored**. DXF-derived gold would grade the solver against its own input |

"Gold-consistent" means the independent instance count equals the official dataset answer. For CubiCasa
that holds on 16,436 of 16,496 test questions (99.6 %): the SVG annotations really are what the official
answers were counted from. Every number below uses all questions unless marked otherwise.

## Results (test split, router v4)

_Re-run on the shipped router (`runs/router_full_test_v7.jsonl`, YOLO11m detector with flip test-time augmentation;
`analysis/out/evidence_hitrate.csv`): CubiCasa, all 16,496 questions: precision 90.7 % / 92.4 % / **95.1 %**, recall
87.2 % / 88.9 % / **91.4 %** (IoU≥.5 / centre / either), count right 85.1 %, count right AND boxes right 83.2 %, of
right counts boxes right **97.7 %** (2.3 % right by luck). The v6 run (no flip): 95.2 % / 90.2 %, count right 84.2 %,
82.2 %, 97.6 %. The detailed tables below are still the v4 run (YOLO11s detector)._

| source | target | questions | our boxes | gold instances | precision IoU≥.5 / centre / either | recall IoU≥.5 / centre / either | count right | count right AND boxes right (either) | of right counts, boxes right |
|---|---|---|---|---|---|---|---|---|---|
| **cubicasa5k** | **all** | 16,496 | 43,984 | 44,416 | 87.9 % / 89.8 % / **92.4 %** | 87.1 % / 89.0 % / **91.5 %** | 82.2 % | **80.1 %** | **97.4 %** |
| cubicasa5k | floor (storeys) | 1,844 | 2,282 | 2,272 | 98.0 / 98.6 / 98.7 | 98.4 / 99.0 / 99.1 | 97.7 | 97.6 | 99.9 |
| cubicasa5k | kitchen | 1,274 | 1,250 | 1,250 | 92.0 / 97.3 / 97.9 | 92.0 / 97.3 / 97.9 | 97.0 | 96.4 | 99.4 |
| cubicasa5k | WC room | 906 | 422 | 468 | 95.3 / 97.2 / 97.2 | 85.9 / 87.6 / 87.6 | 92.9 | 92.9 | 100.0 |
| cubicasa5k | sauna | 1,298 | 782 | 740 | 85.4 / 89.5 / 90.0 | 90.3 / 94.6 / 95.1 | 93.4 | 92.6 | 99.2 |
| cubicasa5k | toilet | 1,840 | 2,468 | 2,542 | 70.4 / 70.7 / 94.3 | 68.4 / 68.6 / 91.6 | 89.9 | 87.4 | 97.2 |
| cubicasa5k | bathroom | 916 | 842 | 892 | 94.1 / 94.8 / 94.8 | 88.8 / 89.5 / 89.5 | 86.5 | 85.8 | 99.2 |
| cubicasa5k | bedroom | 1,162 | 1,932 | 1,914 | 92.8 / 92.9 / 92.9 | 93.6 / 93.7 / 93.7 | 85.5 | 85.0 | 99.4 |
| cubicasa5k | sink | 1,812 | 4,634 | 4,680 | 91.3 / 92.5 / 92.7 | 90.4 / 91.6 / 91.8 | 81.8 | 78.1 | 95.5 |
| cubicasa5k | balcony | 564 | 204 | 252 | 90.2 / 90.2 / 90.2 | 73.0 / 73.0 / 73.0 | 81.6 | 80.1 | 98.3 |
| cubicasa5k | shower + bathtub | 1,710 | 1,950 | 2,012 | 55.9 / 60.0 / 82.0 | 54.2 / 58.1 / 79.4 | 76.5 | 72.5 | 94.8 |
| cubicasa5k | door | 1,326 | 11,434 | 11,382 | 95.8 / 96.1 / 96.2 | 96.3 / 96.6 / 96.6 | 72.4 | 68.3 | 94.4 |
| cubicasa5k | window | 1,844 | 15,784 | 16,012 | 85.2 / 88.5 / 89.1 | 84.0 / 87.2 / 87.8 | 44.7 | 40.5 | 90.5 |
| **swiss_dwellings** | **door** | 386 | 11,501 | 11,501 | 71.5 % / 99.7 % / **100.0 %** | 71.5 % / 99.7 % / **100.0 %** | 100.0 % | **100.0 %** | 100.0 % |
| swiss_dwellings | window (gold-consistent) | 203 | 2,621 | 2,621 | 0.6 / 98.3 / **99.5** | 0.6 / 98.3 / **99.5** | 100.0 | **98.0** | 98.0 |
| **ifc_models** | **per-sheet questions, all** | 82 | 1,404 | 1,718 | 100 (by construction) | **81.7 %** | 100.0 % | **82.9 %** | 82.9 % |
| ifc_models | door / room / stair (per sheet) | 42 | 710 | 710 | 100 | 100 | 100 | 100 | 100 |
| ifc_models | window (per sheet) | 18 | 434 | 486 | 100 | 89.3 | 100 | 66.7 | 66.7 |
| ifc_models | wall (per sheet) | 20 | 260 | 522 | 100 | 49.8 | 100 | 60.0 | 60.0 |
| ifc_models | model-wide questions (boxes on this sheet only) | 38 | 264 | 364 | 100 | 72.5 | 100 | 79.0 | 79.0 |

Questions include the language twins (each CubiCasa drawing×target is asked in English and Finnish with the
same boxes): 16,496 CubiCasa questions are 8,248 distinct (drawing, target) pairs on 922 drawings, and the
Swiss rows are 228 floors asked in English and German. Twins get identical boxes, so the rates are the same
with or without them.

## What this says

- **When the number is right, the boxes are right.** On CubiCasa, 97.4 % of correct counts have every box on
  a real instance and every instance boxed (either-centre rule; 90.6 % under the strict IoU ≥ 0.5 rule).
  Only 352 of 13,566 correct counts (2.6 %) are right by luck, where a missed object and a false box cancel out.
  Swiss doors and windows: 100 % and 98 %. IFC: every box is an element of the right class on the right storey.
- **When the number is wrong, the boxes show why.** Of the 2,930 wrong CubiCasa counts, 1,322 have
  every box on a real instance, so the error is visible missed objects, not invented ones. Under-counts
  (1,480) and over-counts (1,420) are balanced. Windows are the weak class: 89 % of window boxes are
  real windows, but with ~9 windows per plan one miss or one extra is enough to get the count wrong (44.7 %).
  A reviewer sees which window is unboxed.
- **Box-level precision and recall are close to 90 %** on CubiCasa across 44k gold instances: 92.4 % /
  91.5 % (either-centre), 87.9 % / 87.1 % (IoU ≥ 0.5).

## Notes and caveats

- **Thin or partial gold boxes.** CubiCasa's SVG outline for some fixtures covers only part of the symbol.
  For a WC it is often just the cistern strip, while our box covers the whole drawn toilet (checked
  visually on `colorful-6113`: our boxes contain the gold strips). This is why toilet and shower/bathtub IoU
  is low (70 % and 56 %) while either-centre is 94 % and 82 %. Swiss window gold is a group of thin glazing
  lines, so its IoU against any padded box is near zero by geometry; the centre rules are the meaningful
  ones there. Swiss door IoU is 71.5 % because our door box (from the DXF door block, 5 % padding) and the
  PDF swing arc have different extents. The centres match 99.7 %.
- **Zero answers have no boxes.** 2,282 CubiCasa answers are 0 with no boxes (1,814 of them correct).
  They count in "count right AND boxes right" only when the gold also has 0 instances.
- **IFC precision is by construction** (same SVG), so we do not claim it as a vision result. The IFC
  numbers measure element selection and 2D coverage. The 3D evidence (IFC GlobalIds lit up in the
  viewer) covers every counted element, including those missing from the 2D boxes.

## Bug found: cut elements get no 2D box on IFC plan sheets

`bp/ifc/plan2d.py` matches SVG groups with `class="(Ifc\w+)"`, but IfcConvert writes elements that the plan
cut passes through as `class="cut IfcWall"` / `class="cut IfcWindow"` / `class="cut IfcDoor"`. Those
groups never match, so **cut walls, windows and doors get no 2D evidence box**, even though the answer and
the 3D evidence are right. Every IFC recall miss above is such a cut element. Examples (gold = our parser,
which reads the `cut` classes):

| question id | sheet | asked | answer (correct) | 2D boxes shown | cut elements on the sheet |
|---|---|---|---|---|---|
| 89016 | bimspeed-warmond_ar_plan-05-2-level.pdf | walls on '2. Level' | 84 | 0 | 84 IfcWall |
| 88874 | bimspeed-warmond_ar_plan-02-entrance.pdf | windows on 'Entrance' | 22 | 0 | 22 IfcWindow |
| 88464 | bimspeed-frigento_…_plan-02-0-piano-terra.pdf | walls on '0_Piano terra' | 32 | 0 | 32 IfcWall |
| 89264 | bimspeed-warmond_ar_plan-08-attic.pdf | walls on 'Attic' | 9 | 0 | 9 IfcWall |

Suggested fix (not applied; solver code is out of scope for this analysis): use
`class="(?:[^"]*\s)?(Ifc\w+)"` in `_G`. All Warmond and Frigento sheets would then get their wall, window
and door boxes. On the per-sheet questions, wall recall would go from 49.8 % to 100 % and window recall from 89.3 % to 100 %: all 22 IFC questions with missing boxes have zero boxes, and every one of their gold elements is a `cut` element.
