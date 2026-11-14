# crosscheck_test: does a second, independent method confirm the answer?

Test split (by drawing), `router` primary on swiss_dwellings + ifc_models + cubicasa5k (25,310 questions; ifc_bench free
text has no second method and was not run). Log `runs/crosscheck_test.jsonl` from
`eval.py --solver router --split test --source swiss_dwellings --source ifc_models --source cubicasa5k --crosscheck`;
tables from `analysis/crosscheck_report.py`. Nothing below was tuned on test: CubiCasa thresholds and every
"which kinds get a second method" switch come from dev (see `bp/crosscheck.py`). Question counts include each
language variant of the same question (usually 2), so e.g. 6 Swiss conflicts = 3 drawings x question.

## Second methods and how independent they are

| source | primary reads | second method reads | independence |
|---|---|---|---|
| swiss_dwellings | DXF layers | the PDF only: text layer (room labels, numbers, unit labels), room fill polygons x printed 1:n scale (areas), door / fixture symbols from vector paths | medium-high: different file, renderer and parser; same underlying dataset geometry |
| ifc_models | IFC model (IfcOpenShell) | the SVG twin of the storey's plan sheet: elements by class + GUID, IfcSpace footprint polygons x 1:n | medium: rendered from the same IFC; catches query / storey / filter errors, not modelling errors |
| cubicasa5k | YOLO11s detector (1024/1280 px, calibrated counting) | a separately trained YOLO11m (1280 px, snapshot of an in-progress run) with its own dev-tuned count thresholds | low: same public training annotations, similar architecture, so errors correlate |

Not covered (status "single"): Swiss window counts (PDF window symbols matched the DXF on only 86 % of dev
questions), IFC wall / stair / model-wide window counts (not comparable on the sheet on dev), IFC volume /
length / side-area sums, rooms whose name is not on the sheet.

## By source

| group | n | primary acc | coverage | agree | conflict | acc on agree | acc on conflict | acc on single | conflict precision | recall (all wrong) | recall (covered wrong) | 2nd right on conflict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cubicasa5k | 16496 | 82.2% | 100.0% | 80.2% | 3262 | 90.7% | 47.8% | - | 52.2% | 58.1% | 58.1% | 28.0% |
| swiss_dwellings | 8214 | 100.0% | 94.4% | 99.9% | 6 | 100.0% | 66.7% | 100.0% | 33.3% | 50.0% | 50.0% | 33.3% |
| ifc_models | 600 | 100.0% | 72.7% | 99.1% | 4 | 100.0% | 100.0% | 100.0% | 0.0% | - | - | 0.0% |
| **ALL** | 25310 | 88.4% | 97.6% | 86.7% | 3272 | 94.3% | 47.9% | 100.0% | 52.1% | 58.1% | 58.1% | 28.0% |

## By source and question kind

| group | n | primary acc | coverage | agree | conflict | acc on agree | acc on conflict | acc on single | conflict precision | recall (all wrong) | recall (covered wrong) | 2nd right on conflict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| swiss / count_label | 2774 | 100.0% | 100.0% | 100.0% | 0 | 100.0% | - | - | - | - | - | - |
| cubicasa5k / floor | 1844 | 97.7% | 100.0% | 93.7% | 116 | 99.1% | 77.6% | - | 22.4% | 61.9% | 61.9% | 19.0% |
| cubicasa5k / window | 1844 | 44.7% | 100.0% | 48.7% | 946 | 65.5% | 24.9% | - | 75.1% | 69.6% | 69.6% | 26.8% |
| cubicasa5k / toilet | 1840 | 89.9% | 100.0% | 90.5% | 174 | 94.1% | 49.4% | - | 50.6% | 47.3% | 47.3% | 35.6% |
| cubicasa5k / sink | 1812 | 81.8% | 100.0% | 80.7% | 350 | 91.0% | 43.4% | - | 56.6% | 60.0% | 60.0% | 33.1% |
| cubicasa5k / shower_bath | 1710 | 76.5% | 100.0% | 71.1% | 494 | 85.5% | 54.3% | - | 45.7% | 56.2% | 56.2% | 27.1% |
| cubicasa5k / door | 1326 | 72.4% | 100.0% | 72.1% | 370 | 79.1% | 55.1% | - | 44.9% | 45.4% | 45.4% | 24.3% |
| cubicasa5k / sauna | 1298 | 93.4% | 100.0% | 92.1% | 102 | 96.3% | 58.8% | - | 41.2% | 48.8% | 48.8% | 37.3% |
| cubicasa5k / kitchen | 1274 | 97.0% | 100.0% | 82.9% | 218 | 97.2% | 96.3% | - | 3.7% | 21.1% | 21.1% | 2.8% |
| cubicasa5k / bedroom | 1162 | 85.5% | 100.0% | 83.8% | 188 | 92.0% | 52.1% | - | 47.9% | 53.6% | 53.6% | 33.0% |
| cubicasa5k / bathroom | 916 | 86.5% | 100.0% | 82.1% | 164 | 93.6% | 53.7% | - | 46.3% | 61.3% | 61.3% | 41.5% |
| swiss / area_room | 908 | 100.0% | 100.0% | 100.0% | 0 | 100.0% | - | - | - | - | - | - |
| cubicasa5k / wc_room | 906 | 92.9% | 100.0% | 91.8% | 74 | 98.1% | 35.1% | - | 64.9% | 75.0% | 75.0% | 56.8% |
| swiss / area_apartment | 822 | 99.8% | 100.0% | 99.8% | 2 | 100.0% | 0.0% | - | 100.0% | 100.0% | 100.0% | 100.0% |
| cubicasa5k / balcony | 564 | 81.6% | 100.0% | 88.3% | 66 | 83.9% | 63.6% | - | 36.4% | 23.1% | 23.1% | 30.3% |
| swiss / area_numbered | 456 | 100.0% | 100.0% | 100.0% | 0 | 100.0% | - | - | - | - | - | - |
| swiss / count_symbol apartment | 456 | 100.0% | 100.0% | 100.0% | 0 | 100.0% | - | - | - | - | - | - |
| swiss / count_symbol door | 456 | 100.0% | 100.0% | 100.0% | 0 | 100.0% | - | - | - | - | - | - |
| swiss / count_symbol toilet | 456 | 100.0% | 100.0% | 99.6% | 2 | 100.0% | 100.0% | - | 0.0% | - | - | 0.0% |
| swiss / count_symbol washbasin | 456 | 99.6% | 100.0% | 100.0% | 0 | 99.6% | - | - | - | 0.0% | 0.0% | - |
| swiss / count_symbol window | 456 | 100.0% | 0.0% | - | 0 | - | - | 100.0% | - | - | - | - |
| swiss / area_label | 448 | 100.0% | 100.0% | 100.0% | 0 | 100.0% | - | - | - | - | - | - |
| swiss / count_symbol bathtub | 392 | 100.0% | 100.0% | 99.5% | 2 | 100.0% | 100.0% | - | 0.0% | - | - | 0.0% |
| ifc_models / area | 390 | 100.0% | 94.4% | 100.0% | 0 | 100.0% | - | 100.0% | - | - | - | - |
| ifc_models / count | 136 | 100.0% | 50.0% | 94.1% | 4 | 100.0% | 100.0% | 100.0% | 0.0% | - | - | 0.0% |
| swiss / count_symbol shower | 134 | 100.0% | 100.0% | 100.0% | 0 | 100.0% | - | - | - | - | - | - |
| ifc_models / volume | 52 | 100.0% | 0.0% | - | 0 | - | - | 100.0% | - | - | - | - |
| ifc_models / length | 22 | 100.0% | 0.0% | - | 0 | - | - | 100.0% | - | - | - | - |
| **ALL** | 25310 | 88.4% | 97.6% | 86.7% | 3272 | 94.3% | 47.9% | 100.0% | 52.1% | 58.1% | 58.1% | 28.0% |

## Second methods used

| source | method | answers checked |
|---|---|---|
| cubicasa5k | cubicasa-yolo11m-2nd | 16496 |
| swiss_dwellings | swiss-pdf-text | 3230 |
| swiss_dwellings | swiss-pdf-geometry | 2634 |
| swiss_dwellings | swiss-pdf-vectors | 1894 |
| ifc_models | ifc-svg-footprint | 368 |
| ifc_models | ifc-svg-sheet | 68 |

## CubiCasa on dev (YOLO-validation drawings, never trained on): the same picture

| group | n | primary acc | coverage | agree | conflict | acc on agree | acc on conflict | acc on single | conflict precision | recall (all wrong) | recall (covered wrong) | 2nd right on conflict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cubicasa5k | 6378 | 83.5% | 100.0% | 83.0% | 1082 | 91.5% | 44.2% | - | 55.8% | 57.3% | 57.3% | 28.1% |
| **ALL** | 6378 | 83.5% | 100.0% | 83.0% | 1082 | 91.5% | 44.2% | - | 55.8% | 57.3% | 57.3% | 28.1% |

## By source and question kind

| group | n | primary acc | coverage | agree | conflict | acc on agree | acc on conflict | acc on single | conflict precision | recall (all wrong) | recall (covered wrong) | 2nd right on conflict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cubicasa5k / floor | 728 | 97.5% | 100.0% | 94.5% | 40 | 98.5% | 80.0% | - | 20.0% | 44.4% | 44.4% | 15.0% |
| cubicasa5k / window | 728 | 47.0% | 100.0% | 53.8% | 336 | 68.4% | 22.0% | - | 78.0% | 67.9% | 67.9% | 22.0% |
| cubicasa5k / toilet | 724 | 92.0% | 100.0% | 92.8% | 52 | 93.8% | 69.2% | - | 30.8% | 27.6% | 27.6% | 19.2% |
| cubicasa5k / sink | 718 | 82.5% | 100.0% | 81.9% | 130 | 93.2% | 33.8% | - | 66.2% | 68.3% | 68.3% | 43.1% |
| cubicasa5k / shower_bath | 684 | 78.7% | 100.0% | 76.0% | 164 | 86.9% | 52.4% | - | 47.6% | 53.4% | 53.4% | 32.9% |
| cubicasa5k / door | 506 | 73.1% | 100.0% | 79.8% | 102 | 80.2% | 45.1% | - | 54.9% | 41.2% | 41.2% | 23.5% |
| cubicasa5k / sauna | 486 | 94.2% | 100.0% | 92.2% | 38 | 97.8% | 52.6% | - | 47.4% | 64.3% | 64.3% | 36.8% |
| cubicasa5k / kitchen | 472 | 94.1% | 100.0% | 80.5% | 92 | 97.4% | 80.4% | - | 19.6% | 64.3% | 64.3% | 17.4% |
| cubicasa5k / bedroom | 436 | 87.2% | 100.0% | 89.0% | 48 | 92.3% | 45.8% | - | 54.2% | 46.4% | 46.4% | 33.3% |
| cubicasa5k / bathroom | 358 | 90.5% | 100.0% | 89.4% | 38 | 94.4% | 57.9% | - | 42.1% | 47.1% | 47.1% | 42.1% |
| cubicasa5k / wc_room | 340 | 93.5% | 100.0% | 92.4% | 26 | 98.1% | 38.5% | - | 61.5% | 72.7% | 72.7% | 53.8% |
| cubicasa5k / balcony | 198 | 91.9% | 100.0% | 91.9% | 16 | 93.4% | 75.0% | - | 25.0% | 25.0% | 25.0% | 25.0% |
| **ALL** | 6378 | 83.5% | 100.0% | 83.0% | 1082 | 91.5% | 44.2% | - | 55.8% | 57.3% | 57.3% | 28.1% |

## What it shows

- **Swiss** (94 % covered, 99.9 % agree): 6 conflicts = 3 drawings x 2 languages. One (apartment A area) is a
  real primary error: DXF 86.72 m², PDF geometry 95.38 m², gold 95.36. The other two are second-method misreads
  (one bathtub, one WC symbol), so conflict precision 1 of 3 drawings. The 2 other wrong primary answers (washbasins 3 vs
  gold 4) were *agreed* by the PDF: both readings come from the same drawn geometry, so a symbol missing from
  the drawing cannot be caught by re-reading it.
- **IFC** (73 % covered, 99.1 % agree): the primary was right on every test question; 4 conflicts are false
  alarms (model-wide door counts where some doors are not cut at 1.2 m on any sheet). Room areas: 368
  checked, 0 conflicts (Qto NetFloorArea vs SVG footprint within 2 %).
- **CubiCasa** (100 % covered, 80 % agree): accuracy is 90.7 % when the two detectors agree vs 47.8 % on
  conflict (82.2 % overall). Conflict precision 52 % (base error rate 18 %), recall 58 % of all wrong answers.
  But it is mostly the *same* information as the primary's calibrated confidence: abstaining on the
  lowest-confidence 20 % gives 92.5 % on the rest, vs 90.7 % for abstaining on conflict. Combined
  (confidence x 0.5 on conflict) at 80 % coverage: 93.3 % (dev 92.4 % vs 91.7 % confidence-only), i.e. +0.5 to
  +0.8 pt. When they disagree, the second detector is right only 28 % of the time, so it must not override.

## Proposed router rule (not applied)

1. On **conflict**, keep the primary answer but multiply its confidence by 0.5 and show both sets of marks
   ("conflict: 5 vs 6"). On CubiCasa this ranks answers slightly better than confidence alone (+0.7 pt dev,
   +0.8 pt test at 80 % coverage); with the router's 0.5 abstain threshold it turns most conflicts into "not sure".
2. Do **not** prefer the second method (right on 28 % of CubiCasa conflicts; 1 of 3 Swiss conflict drawings).
3. Swiss / IFC conflicts are rare (10 of 8,814 questions) and need a human look: show the conflict, don't abstain.
4. Use **agree** as the "verified" badge: 100 % accurate on Swiss and IFC test, 90.7 % on CubiCasa.
