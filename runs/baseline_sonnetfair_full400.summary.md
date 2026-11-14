# baseline_sonnetfair_full400

solver `claude@sonnet+twins`, split `test`, n=400, questions of `runs/baseline_sonnet_full400.jsonl`

**Headline (as quoted in README / docs/RESULTS.md): 69.8% [60.9%, 78.4%], re-weighted, stratified bootstrap to the held-out test mix, text answers scored by the LLM judge; API cost $25.76 / 1k questions.** The tables below are unweighted means over this sample as logged (text by the token-F1 proxy); the unweighted mean with judge verdicts is 75.8%. Both differ from the headline.

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| count | 163 | 100% | 80.4% | 80.4% | 24.24 | 11.22 |
| area | 108 | 100% | 88.9% | 88.9% | 68.82 | 26.84 |
| text | 55 | 91% | 1.8% | 2.0% | 106.86 | 35.00 |
| volume | 52 | 100% | 98.1% | 98.1% | 89.97 | 18.00 |
| length | 22 | 100% | 90.9% | 90.9% | 117.45 | 21.64 |
| **ALL** | 400 | 99% | 74.8% | 75.7% | 61.31 | 20.16 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_models | 182 | 100% | 96.7% | 96.7% | 58.22 | 13.47 |
| swiss_dwellings | 108 | 100% | 80.6% | 80.6% | 69.28 | 27.79 |
| cubicasa5k | 55 | 100% | 63.6% | 63.6% | 10.31 | 12.48 |
| ifc_bench | 55 | 91% | 1.8% | 2.0% | 106.86 | 35.00 |
| **ALL** | 400 | 99% | 74.8% | 75.7% | 61.31 | 20.16 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| cubicasa5k / count | 55 | 100% | 63.6% | 63.6% | 10.31 | 12.48 |
| ifc_bench / text | 55 | 91% | 1.8% | 2.0% | 106.86 | 35.00 |
| ifc_models / area | 54 | 100% | 98.1% | 98.1% | 28.02 | 10.07 |
| ifc_models / count | 54 | 100% | 96.3% | 96.3% | 33.73 | 9.19 |
| swiss_dwellings / area | 54 | 100% | 79.6% | 79.6% | 109.62 | 43.60 |
| swiss_dwellings / count | 54 | 100% | 81.5% | 81.5% | 28.94 | 11.97 |
| ifc_models / volume | 52 | 100% | 98.1% | 98.1% | 89.97 | 18.00 |
| ifc_models / length | 22 | 100% | 90.9% | 90.9% | 117.45 | 21.64 |
| **ALL** | 400 | 99% | 74.8% | 75.7% | 61.31 | 20.16 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 225 | 98% | 65.8% | 67.3% | 69.05 | 21.96 |
| de | 73 | 100% | 80.8% | 80.8% | 59.62 | 19.68 |
| nl | 49 | 100% | 100.0% | 100.0% | 56.97 | 14.05 |
| fi | 27 | 100% | 70.4% | 70.4% | 10.21 | 12.79 |
| fr | 16 | 100% | 87.5% | 87.5% | 64.13 | 25.45 |
| it | 10 | 100% | 100.0% | 100.0% | 54.19 | 24.64 |
| **ALL** | 400 | 99% | 74.8% | 75.7% | 61.31 | 20.16 |
