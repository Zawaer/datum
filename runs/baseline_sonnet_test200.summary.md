# baseline_sonnet_test200

solver `claude@sonnet`, split `test`, n=200, stratified sample 200

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| count | 133 | 100% | 85.0% | 85.0% | 12.68 | 6.14 |
| area | 61 | 100% | 36.1% | 36.1% | 21.59 | 10.38 |
| volume | 4 | 100% | 0.0% | 0.0% | 22.83 | 11.88 |
| length | 2 | 100% | 0.0% | 0.0% | 19.48 | 10.76 |
| **ALL** | 200 | 100% | 67.5% | 67.5% | 15.67 | 7.59 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| swiss_dwellings | 117 | 100% | 60.7% | 60.7% | 18.47 | 8.30 |
| cubicasa5k | 59 | 100% | 84.7% | 84.7% | 9.19 | 5.82 |
| ifc_models | 24 | 100% | 58.3% | 58.3% | 17.91 | 8.52 |
| **ALL** | 200 | 100% | 67.5% | 67.5% | 15.67 | 7.59 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| cubicasa5k / count | 59 | 100% | 84.7% | 84.7% | 9.19 | 5.82 |
| swiss_dwellings / area | 59 | 100% | 37.3% | 37.3% | 21.48 | 10.23 |
| swiss_dwellings / count | 58 | 100% | 84.5% | 84.5% | 15.42 | 6.34 |
| ifc_models / count | 16 | 100% | 87.5% | 87.5% | 15.63 | 6.61 |
| ifc_models / volume | 4 | 100% | 0.0% | 0.0% | 22.83 | 11.88 |
| ifc_models / area | 2 | 100% | 0.0% | 0.0% | 24.77 | 14.80 |
| ifc_models / length | 2 | 100% | 0.0% | 0.0% | 19.48 | 10.76 |
| **ALL** | 200 | 100% | 67.5% | 67.5% | 15.67 | 7.59 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 101 | 100% | 66.3% | 66.3% | 15.64 | 7.46 |
| de | 36 | 100% | 55.6% | 55.6% | 19.17 | 8.78 |
| fi | 33 | 100% | 84.8% | 84.8% | 8.96 | 5.77 |
| it | 15 | 100% | 66.7% | 66.7% | 17.03 | 7.48 |
| fr | 15 | 100% | 66.7% | 66.7% | 20.85 | 9.74 |
| **ALL** | 200 | 100% | 67.5% | 67.5% | 15.67 | 7.59 |
