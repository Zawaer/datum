# baseline_nemotron_full400

solver `nemotron`, split `test`, n=400, questions of `runs/baseline_sonnet_full400.jsonl`

**Headline (as quoted in README / docs/RESULTS.md): 49.0% [40.0%, 58.0%], re-weighted, stratified bootstrap to the held-out test mix, text answers scored by the LLM judge; API cost $2.59 / 1k questions.** The tables below are unweighted means over this sample as logged (text by the token-F1 proxy); the unweighted mean with judge verdicts is 22.5%. Both differ from the headline.

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| count | 163 | 93% | 48.5% | 52.3% | 2.38 | 34.92 |
| area | 108 | 81% | 8.3% | 10.3% | 4.16 | 66.47 |
| text | 55 | 0% | 0.0% | - | 0.00 | 0.00 |
| volume | 52 | 81% | 1.9% | 2.4% | 4.52 | 67.71 |
| length | 22 | 55% | 0.0% | 0.0% | 6.90 | 102.05 |
| **ALL** | 400 | 73% | 22.2% | 30.5% | 3.06 | 46.59 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_models | 182 | 81% | 7.7% | 9.5% | 3.71 | 52.79 |
| swiss_dwellings | 108 | 83% | 45.4% | 54.4% | 3.94 | 66.73 |
| cubicasa5k | 55 | 98% | 47.3% | 48.1% | 2.24 | 33.13 |
| ifc_bench | 55 | 0% | 0.0% | - | 0.00 | 0.00 |
| **ALL** | 400 | 73% | 22.2% | 30.5% | 3.06 | 46.59 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| cubicasa5k / count | 55 | 98% | 47.3% | 48.1% | 2.24 | 33.13 |
| ifc_bench / text | 55 | 0% | 0.0% | - | 0.00 | 0.00 |
| ifc_models / count | 54 | 81% | 22.2% | 27.3% | 2.75 | 38.25 |
| ifc_models / area | 54 | 93% | 1.9% | 2.0% | 2.60 | 32.89 |
| swiss_dwellings / count | 54 | 98% | 75.9% | 77.4% | 2.16 | 33.42 |
| swiss_dwellings / area | 54 | 69% | 14.8% | 21.6% | 5.71 | 100.05 |
| ifc_models / volume | 52 | 81% | 1.9% | 2.4% | 4.52 | 67.71 |
| ifc_models / length | 22 | 55% | 0.0% | 0.0% | 6.90 | 102.05 |
| **ALL** | 400 | 73% | 22.2% | 30.5% | 3.06 | 46.59 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 225 | 64% | 18.2% | 28.5% | 2.73 | 40.51 |
| de | 73 | 73% | 26.0% | 35.8% | 4.33 | 71.54 |
| nl | 49 | 90% | 4.1% | 4.5% | 3.20 | 42.50 |
| fi | 27 | 96% | 48.1% | 50.0% | 2.20 | 32.10 |
| fr | 16 | 94% | 62.5% | 66.7% | 3.10 | 53.56 |
| it | 10 | 100% | 40.0% | 40.0% | 2.70 | 49.38 |
| **ALL** | 400 | 73% | 22.2% | 30.5% | 3.06 | 46.59 |

**61 questions hit a solver error** (they count as abstains):

- 61 x `.ifc is not an image`
