# baseline_sonnet_twins_full400

solver `claude@sonnet+twins`, split `test`, n=284

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| area | 108 | 100% | 65.7% | 65.7% | 63.58 | 24.60 |
| count | 102 | 100% | 85.3% | 85.3% | 31.89 | 10.20 |
| volume | 52 | 100% | 82.7% | 82.7% | 77.83 | 14.91 |
| length | 22 | 100% | 81.8% | 81.8% | 108.80 | 19.97 |
| **ALL** | 284 | 100% | 77.1% | 77.1% | 58.31 | 17.29 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_models | 176 | 100% | 75.0% | 75.0% | 51.57 | 10.86 |
| swiss_dwellings | 108 | 100% | 80.6% | 80.6% | 69.28 | 27.79 |
| **ALL** | 284 | 100% | 77.1% | 77.1% | 58.31 | 17.29 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_models / area | 54 | 100% | 51.9% | 51.9% | 17.54 | 5.59 |
| swiss_dwellings / count | 54 | 100% | 81.5% | 81.5% | 28.94 | 11.97 |
| swiss_dwellings / area | 54 | 100% | 79.6% | 79.6% | 109.62 | 43.60 |
| ifc_models / volume | 52 | 100% | 82.7% | 82.7% | 77.83 | 14.91 |
| ifc_models / count | 48 | 100% | 89.6% | 89.6% | 35.20 | 8.21 |
| ifc_models / length | 22 | 100% | 81.8% | 81.8% | 108.80 | 19.97 |
| **ALL** | 284 | 100% | 77.1% | 77.1% | 58.31 | 17.29 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 138 | 100% | 79.7% | 79.7% | 62.51 | 17.58 |
| de | 71 | 100% | 80.3% | 80.3% | 61.01 | 19.93 |
| nl | 49 | 100% | 57.1% | 57.1% | 41.50 | 8.50 |
| fr | 16 | 100% | 87.5% | 87.5% | 64.13 | 25.45 |
| it | 10 | 100% | 100.0% | 100.0% | 54.19 | 24.64 |
| **ALL** | 284 | 100% | 77.1% | 77.1% | 58.31 | 17.29 |
