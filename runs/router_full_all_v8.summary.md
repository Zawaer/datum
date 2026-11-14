# router_full_all_v8

**Full dataset, all 127,044 questions (every split): 91.3%.** This number is mostly IN-SAMPLE: 101,624 of the questions are on drawings we trained the detector on or tuned rules / thresholds on. Held-out test part alone: 90.7% (n=25,420); in-sample part alone: 91.4% (n=101,624). The published held-out headline stays router_full_test_v8.

Solver `router` (shipped pipeline: flip-TTA YOLO11m v4 + VLM arbiter for CubiCasa), text answers scored by the LLM judge, abstain = wrong. Built by analysis/full_dataset.py.

Splits:

- `test`: test (held out: never trained or tuned on)
- `cc-dev-val`: CubiCasa dev-val (in-sample for thresholds / calibration / arbiter; detector never trained on it)
- `cc-train`: CubiCasa detector-training drawings (in-sample for the detector)
- `dev`: other sources' dev drawings (in-sample: rules and prompts developed on them)

## By split
| group | n | accuracy |
|---|---|---|
| cc-train | 62640 | 88.0% |
| dev | 32606 | 99.1% |
| test | 25420 | 90.7% |
| cc-dev-val | 6378 | 86.5% |
| **ALL** | 127044 | 91.3% |

## By source
| group | n | accuracy |
|---|---|---|
| cubicasa5k | 85514 | 87.5% |
| swiss_dwellings | 37584 | 100.0% |
| ifc_models | 3062 | 100.0% |
| ifc_bench | 820 | 55.2% |
| opening_design | 64 | 95.3% |
| **ALL** | 127044 | 91.3% |

## By split and source
| group | n | accuracy |
|---|---|---|
| cc-train / cubicasa5k | 62640 | 88.0% |
| dev / swiss_dwellings | 29370 | 100.0% |
| test / cubicasa5k | 16496 | 86.1% |
| test / swiss_dwellings | 8214 | 100.0% |
| cc-dev-val / cubicasa5k | 6378 | 86.5% |
| dev / ifc_models | 2462 | 100.0% |
| dev / ifc_bench | 710 | 57.9% |
| test / ifc_models | 600 | 100.0% |
| test / ifc_bench | 110 | 38.2% |
| dev / opening_design | 64 | 95.3% |
| **ALL** | 127044 | 91.3% |

## By source and type
| group | n | accuracy |
|---|---|---|
| cubicasa5k / count | 85514 | 87.5% |
| swiss_dwellings / count | 25568 | 100.0% |
| swiss_dwellings / area | 12016 | 100.0% |
| ifc_models / area | 2218 | 100.0% |
| ifc_bench / text | 820 | 55.2% |
| ifc_models / count | 642 | 100.0% |
| ifc_models / volume | 138 | 100.0% |
| ifc_models / length | 64 | 100.0% |
| opening_design / count | 39 | 97.4% |
| opening_design / text | 16 | 87.5% |
| opening_design / area | 9 | 100.0% |
| **ALL** | 127044 | 91.3% |
