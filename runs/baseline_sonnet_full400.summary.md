# baseline_sonnet_full400

solver `claude@sonnet`, split `test`, n=400, stratified sample 400

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| count | 163 | 100% | 62.0% | 62.0% | 13.90 | 12.82 |
| area | 108 | 100% | 24.1% | 24.1% | 20.48 | 14.86 |
| text | 55 | 91% | 1.8% | 2.0% | 106.86 | 35.00 |
| volume | 52 | 100% | 3.8% | 3.8% | 20.84 | 16.64 |
| length | 22 | 100% | 13.6% | 13.6% | 21.38 | 17.10 |
| **ALL** | 400 | 99% | 33.2% | 33.7% | 29.77 | 17.15 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_models | 182 | 100% | 18.1% | 18.1% | 19.42 | 15.18 |
| swiss_dwellings | 108 | 100% | 59.3% | 59.3% | 17.86 | 13.76 |
| cubicasa5k | 55 | 100% | 63.6% | 63.6% | 10.31 | 12.48 |
| ifc_bench | 55 | 91% | 1.8% | 2.0% | 106.86 | 35.00 |
| **ALL** | 400 | 99% | 33.2% | 33.7% | 29.77 | 17.15 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| cubicasa5k / count | 55 | 100% | 63.6% | 63.6% | 10.31 | 12.48 |
| ifc_bench / text | 55 | 91% | 1.8% | 2.0% | 106.86 | 35.00 |
| ifc_models / area | 54 | 100% | 9.3% | 9.3% | 20.29 | 14.48 |
| ifc_models / count | 54 | 100% | 42.6% | 42.6% | 16.38 | 13.71 |
| swiss_dwellings / area | 54 | 100% | 38.9% | 38.9% | 20.66 | 15.23 |
| swiss_dwellings / count | 54 | 100% | 79.6% | 79.6% | 15.06 | 12.29 |
| ifc_models / volume | 52 | 100% | 3.8% | 3.8% | 20.84 | 16.64 |
| ifc_models / length | 22 | 100% | 13.6% | 13.6% | 21.38 | 17.10 |
| **ALL** | 400 | 99% | 33.2% | 33.7% | 29.77 | 17.15 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 225 | 98% | 29.8% | 30.5% | 39.12 | 19.16 |
| de | 73 | 100% | 38.4% | 38.4% | 19.10 | 15.82 |
| nl | 49 | 100% | 6.1% | 6.1% | 20.18 | 13.86 |
| fi | 27 | 100% | 70.4% | 70.4% | 10.21 | 12.79 |
| fr | 16 | 100% | 68.8% | 68.8% | 16.64 | 13.24 |
| it | 10 | 100% | 50.0% | 50.0% | 17.98 | 15.89 |
| **ALL** | 400 | 99% | 33.2% | 33.7% | 29.77 | 17.15 |
