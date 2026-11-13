# baseline_haiku_full400

solver `claude@haiku`, split `test`, n=400, stratified sample 400

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| count | 163 | 100% | 57.1% | 57.1% | 1.26 | 27.40 |
| area | 108 | 100% | 16.7% | 16.7% | 1.74 | 31.27 |
| text | 55 | 69% | 1.8% | 2.6% | 9.11 | 71.73 |
| volume | 52 | 100% | 1.9% | 1.9% | 1.44 | 29.03 |
| length | 22 | 100% | 36.4% | 36.4% | 1.75 | 30.93 |
| **ALL** | 400 | 96% | 30.2% | 31.6% | 2.52 | 34.94 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_models | 182 | 100% | 17.0% | 17.0% | 1.58 | 29.83 |
| swiss_dwellings | 108 | 100% | 50.0% | 50.0% | 1.49 | 27.88 |
| cubicasa5k | 55 | 100% | 63.6% | 63.6% | 1.04 | 28.95 |
| ifc_bench | 55 | 69% | 1.8% | 2.6% | 9.11 | 71.73 |
| **ALL** | 400 | 96% | 30.2% | 31.6% | 2.52 | 34.94 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| cubicasa5k / count | 55 | 100% | 63.6% | 63.6% | 1.04 | 28.95 |
| ifc_bench / text | 55 | 69% | 1.8% | 2.6% | 9.11 | 71.73 |
| ifc_models / area | 54 | 100% | 7.4% | 7.4% | 1.78 | 32.61 |
| ifc_models / count | 54 | 100% | 33.3% | 33.3% | 1.45 | 27.37 |
| swiss_dwellings / area | 54 | 100% | 25.9% | 25.9% | 1.70 | 29.92 |
| swiss_dwellings / count | 54 | 100% | 74.1% | 74.1% | 1.29 | 25.84 |
| ifc_models / volume | 52 | 100% | 1.9% | 1.9% | 1.44 | 29.03 |
| ifc_models / length | 22 | 100% | 36.4% | 36.4% | 1.75 | 30.93 |
| **ALL** | 400 | 96% | 30.2% | 31.6% | 2.52 | 34.94 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 225 | 92% | 26.7% | 28.8% | 3.29 | 39.04 |
| de | 73 | 100% | 32.9% | 32.9% | 1.59 | 29.47 |
| nl | 49 | 100% | 6.1% | 6.1% | 1.74 | 32.30 |
| fi | 27 | 100% | 70.4% | 70.4% | 1.09 | 27.89 |
| fr | 16 | 100% | 62.5% | 62.5% | 1.31 | 25.64 |
| it | 10 | 100% | 50.0% | 50.0% | 1.45 | 29.61 |
| **ALL** | 400 | 96% | 30.2% | 31.6% | 2.52 | 34.94 |
