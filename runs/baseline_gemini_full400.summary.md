# baseline_gemini_full400

solver `gemini`, split `test`, n=400

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| count | 163 | 96% | 56.4% | 58.6% | 37.11 | 23.13 |
| area | 108 | 100% | 15.7% | 15.7% | 155.35 | 87.38 |
| text | 55 | 0% | 0.0% | - | 0.00 | 0.00 |
| volume | 52 | 100% | 1.9% | 1.9% | 99.53 | 60.52 |
| length | 22 | 100% | 4.5% | 4.5% | 212.12 | 123.36 |
| **ALL** | 400 | 85% | 27.8% | 32.7% | 81.67 | 47.67 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_models | 182 | 97% | 11.0% | 11.4% | 101.67 | 60.48 |
| swiss_dwellings | 108 | 100% | 48.1% | 48.1% | 111.57 | 62.33 |
| cubicasa5k | 55 | 100% | 70.9% | 70.9% | 38.48 | 24.17 |
| ifc_bench | 55 | 0% | 0.0% | - | 0.00 | 0.00 |
| **ALL** | 400 | 85% | 27.8% | 32.7% | 81.67 | 47.67 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| cubicasa5k / count | 55 | 100% | 70.9% | 70.9% | 38.48 | 24.17 |
| ifc_bench / text | 55 | 0% | 0.0% | - | 0.00 | 0.00 |
| ifc_models / count | 54 | 89% | 29.6% | 33.3% | 54.88 | 32.83 |
| ifc_models / area | 54 | 100% | 3.7% | 3.7% | 105.51 | 62.47 |
| swiss_dwellings / count | 54 | 100% | 68.5% | 68.5% | 17.95 | 12.37 |
| swiss_dwellings / area | 54 | 100% | 27.8% | 27.8% | 205.19 | 112.28 |
| ifc_models / volume | 52 | 100% | 1.9% | 1.9% | 99.53 | 60.52 |
| ifc_models / length | 22 | 100% | 4.5% | 4.5% | 212.12 | 123.36 |
| **ALL** | 400 | 85% | 27.8% | 32.7% | 81.67 | 47.67 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 225 | 74% | 23.6% | 31.9% | 71.66 | 41.83 |
| de | 73 | 97% | 30.1% | 31.0% | 127.98 | 73.75 |
| nl | 49 | 100% | 6.1% | 6.1% | 75.12 | 45.85 |
| fi | 27 | 100% | 70.4% | 70.4% | 51.29 | 29.92 |
| fr | 16 | 100% | 56.2% | 56.2% | 68.55 | 39.31 |
| it | 10 | 100% | 50.0% | 50.0% | 103.95 | 59.06 |
| **ALL** | 400 | 85% | 27.8% | 32.7% | 81.67 | 47.67 |
