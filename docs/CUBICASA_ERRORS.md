# CubiCasa errors: where the 14 % goes, and what (does not) fix it

All analysis here is on the **dev-val** drawings (364 drawings with questions, 6,378 questions). The detector was never
trained on them. Thresholds, calibration and counting rules are **out-of-fold** (2-fold over drawings,
`cv_pipeline.sh` → `cache/cubicasa/tta/cv_flipq_{A,B}`), with the shipped VLM arbiter on top. The test split was not
looked at for any of this.

Tools:
- `train/cubicasa/errsim.py`: offline replica of the shipped pipeline from cached detections. It reproduces
  `cv_flipq.jsonl` on 6,376 of 6,378 questions.
- `train/cubicasa/errors_dev.py`: the tables below, plus overlays (`--render window door ...`): gold boxes are green/blue, our counted boxes red with their score.
- `train/cubicasa/rules_cv.py`: rule fixes, with the per-template choice cross-validated (5-fold × 10 repeats over drawings).
- `train/cubicasa/arbiter2_dev.py`: the arbiter with a second detector's vote, cross-validated.

Dev-val accuracy: detector 84.76 % (out-of-fold), plus the arbiter 86.16 % (arbiter rule fitted on these same drawings; its
cross-validated gain is +0.89 pp, not +1.40).

## What the gold is

The gold count equals the number of matching objects in the drawing's CubiCasa5K `model.svg` annotation on **100 %**
of dev-val drawings, for every symbol template (window, door, toilet, sink, shower/bath). So "correct" means "matches
how the CubiCasa annotator split and covered this drawing", not "matches what a person counts on the plan".

## Breakdown by template (dev-val, out-of-fold detector + arbiter)

| template | n | accuracy | errors | share of all errors | over | under | off by 1 | mean gold |
|---|---|---|---|---|---|---|---|---|
| window | 728 | 49.5% | 368 | 41.7% | 94 | 274 | 154 | 9.2 |
| door | 506 | 76.5% | 119 | 13.5% | 51 | 68 | 90 | 9.1 |
| shower_bath | 684 | 84.9% | 103 | 11.7% | 40 | 63 | 78 | 1.3 |
| sink | 718 | 86.2% | 99 | 11.2% | 53 | 46 | 78 | 2.7 |
| toilet | 724 | 91.6% | 61 | 6.9% | 18 | 43 | 49 | 1.5 |
| bedroom | 436 | 91.5% | 37 | 4.2% | 14 | 23 | 18 | 1.7 |
| kitchen | 472 | 96.0% | 19 | 2.2% | 7 | 12 | 19 | 1.0 |
| bathroom | 358 | 94.7% | 19 | 2.2% | 3 | 16 | 17 | 0.9 |
| sauna | 486 | 96.3% | 18 | 2.0% | 6 | 12 | 18 | 0.6 |
| wc_room | 340 | 95.9% | 14 | 1.6% | 6 | 8 | 14 | 0.6 |
| floor | 728 | 98.1% | 14 | 1.6% | 10 | 4 | 10 | 1.2 |
| balcony | 198 | 93.9% | 12 | 1.4% | 0 | 12 | 12 | 0.4 |

**Windows alone are 42 % of all CubiCasa errors.** Windows, doors, showers and sinks together are 78 %.

### By drawing style (from the CubiCasa5K folder)

| template | colorful | high_quality | high_quality_architectural |
|---|---|---|---|
| window | 66.7% (n=36) | 72.7% (n=132) | **42.9% (n=560)** |
| door | 83.3% (n=24) | 82.6% (n=92) | 74.6% (n=390) |
| sink | 100.0% (n=36) | 90.8% (n=130) | 84.2% (n=552) |
| toilet | 100.0% (n=36) | 93.2% (n=132) | 90.6% (n=556) |
| shower_bath | 82.4% (n=34) | 82.5% (n=120) | 85.7% (n=530) |
| ALL | 90.2% (n=306) | 90.8% (n=1222) | 84.7% (n=4850) |

The scanned architectural drawings (76 % of the questions) are the hard ones. Their windows are thin double lines
in thick walls, often hand-annotated over scans.

### Instance-level causes (counted boxes matched one-to-one to annotated boxes, English questions)

| template | fp (box on nothing) | fn (missed) | split (2 boxes, 1 object) | merge (1 box, 2+ objects) |
|---|---|---|---|---|
| window | 61 | 255 | 48 | **234** |
| door | 55 | 55 | 4 | 7 |
| shower_bath | 58 | 75 | 10 | 9 |
| sink | 52 | 56 | 0 | 1 |
| toilet | 19 | 34 | 0 | 1 |

## What the overlays show

135 wrong drawings were rendered (window 30, door 30, and 25 each for shower/bath, sink and toilet; `cache/cubicasa/errs/`, not in git).
A sample of them was read by eye. The causes below come from that sample together with the instance-level counts above, so
their relative frequencies are estimates.

1. **Window bands: merge vs split is the annotator's choice per drawing.** One detected box over a run of window units on
   a wall, annotated as 2-3 windows (e.g. `high_quality_architectural-10008`: one box at 0.50 covers two annotated
   units). Earlier work (`train/cubicasa/window_units.py`) showed that the convention is per drawing: 66 of 68
   drawings with 2+ such runs are all-split or all-merged, and nothing in the pixels predicts which. Splitting gains
   as many drawings as it loses.
2. **Missed faint windows on scans** (fn 255): thin, low-contrast window symbols in hand-drawn or re-scanned
   architectural plans; the detector's score for them is below every threshold that keeps precision.
3. **Glazed balconies count as windows.** "LAS. PARVEKE" (glazed balcony) edges are annotated as windows
   (`high_quality_architectural-10129`: 3 balcony-glazing windows, none detected). Systematic, but rare and visually
   ambiguous with railings.
4. **Partial annotation.** On commercial and multi-unit sheets the annotator covered one unit or part of the sheet.
   Doors, sinks and WCs outside it are on the plan but not in the gold (`colorful-9207`: gold 2 doors, 7 drawn and
   detected; `high_quality_architectural-10271`: 4 sinks drawn, 1 annotated). Every other error class is noise
   compared with this one for doors and sinks.
5. **Double doors.** A double-leaf door gets one door box plus a small box on the second leaf (`colorful-9207`: 0.60 +
   0.60, 0.71 + 0.66). The annotation counts one door.
6. **Showers annotated as tiny marks.** Some drawings annotate a shower as a few-pixel box at the drain or head
   (`high_quality-3074`). The detector, trained on mostly full-tray boxes, misses them.
7. **Inherent annotation slips.** Windows drawn but not annotated (`high_quality_architectural-10000`), which no counting rule can fix.

Not observed as a material cause: legend/inset symbols, and boxes on the plan border (see the edge rule below).

## Fixes tried (all cross-validated on dev-val, gain vs the shipped pipeline)

| fix | questions gained (dev-val) | CV gain of per-template choice |
|---|---|---|
| count only symbols inside a detected floor box (partial annotation, #4) | −406 (−259 with 2 % padding) | not chosen |
| drop a box ≥ 60 % / 80 % inside a higher-scoring same-template box (duplicates, #5) | −12 / −8 | not chosen |
| drop symbols within 1.5 % of the image border (edges, insets) | −8 | not chosen |
| per-template choice among all of the above | | **−0.04 pp** (95 % CI −0.10 to 0.00) |
| VLM as the primary answer, any template | VLM is below the detector on every template (windows 24 % vs 50 %, doors 39 % vs 76 %) | no |
| arbiter + vote of a second detector: YOLO26x flip | | **+0.33 pp** over the shipped arbiter (95 % CI +0.02 to +0.59) |
| ... second detector = v4 single pass / v4+v5 ensemble / YOLO11x / v4+YOLO26x | | +0.07 / +0.15 / −0.02 / +0.10 (CIs include 0) |
| residual shift (count ± k by predicted count) | residuals are centred on 0 at every predicted count | no |

Only the YOLO26x vote is significant, and barely. It needs a second heavy detector (4 flip passes of an x-size model)
per drawing, several times the CPU cost of the whole current pipeline on the 4-core demo VM. **Not shipped.** With no
dev-selected change, there was no reason to spend the one allowed test run (`router_full_test_v9`), so none was made.
The held-out headline stays `router_full_test_v8`.

## Why not retrain on more data

The router's accuracy on the drawings the detector was **trained on** is only ~88 % (`runs/router_full_all_v8`,
split `cc-train`), barely above dev-val and test (86-87 %). The model cannot even reproduce its own training
annotations, because they are inconsistent between drawings (#1, #4). Another ~10 % of drawings (dev-val) would not
change that. It would also use up the only drawings we can tune thresholds on honestly. A YOLO11m 1280 px run is about
13 epochs per hour on the RTX 4070 (46 epochs, about 3.5-4 h with the GPU shared), so it was not started.

## Image only, by design

The Junction dataset ships CubiCasa drawings as PNG only, renamed `<folder>-<id>.png`. Its `cubicasa5k/LICENSE.md`
links the public CubiCasa5K release, which has `<folder>/<id>/model.svg` for every drawing. Because the gold is the
annotation count, a lookup of that public release would answer the questions without any vision:
`analysis/svg_oracle.py` (an offline measurement that no solver uses; counting rule fixed on dev) scores **99.76 %** on all
16,496 CubiCasa test questions. Datum reads only the image, because real customer scans come without annotations. The
86.1 % CubiCasa and 90.7 % overall figures are image-only on held-out drawings.

## Full dataset (in-sample)

`runs/router_full_all_v8` (`analysis/full_dataset.py`) runs the shipped router on all 127,044 questions: **91.3 %**,
of which 101,624 questions are in-sample (91.4 %). By split: held-out test 90.7 % (identical to `router_full_test_v8`
question for question), CubiCasa detector-training drawings 88.0 %, CubiCasa dev-val 86.5 %, other sources' dev
drawings 99.1 % (Swiss and IFC numeric 100 %, ifc_bench text 57.9 %). This is not a headline figure.
