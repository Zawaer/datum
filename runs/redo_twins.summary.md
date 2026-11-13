# redo_twins

solver `claude@sonnet+twins`, split `test`, n=38

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| area | 25 | 100% | 100.0% | 100.0% | 22.64 | 11.03 |
| volume | 8 | 100% | 100.0% | 100.0% | 83.36 | 21.92 |
| count | 3 | 100% | 100.0% | 100.0% | 38.69 | 14.17 |
| length | 2 | 100% | 100.0% | 100.0% | 118.67 | 26.14 |
| **ALL** | 38 | 100% | 100.0% | 100.0% | 41.74 | 14.37 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_models | 38 | 100% | 100.0% | 100.0% | 41.74 | 14.37 |
| **ALL** | 38 | 100% | 100.0% | 100.0% | 41.74 | 14.37 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_models / area | 25 | 100% | 100.0% | 100.0% | 22.64 | 11.03 |
| ifc_models / volume | 8 | 100% | 100.0% | 100.0% | 83.36 | 21.92 |
| ifc_models / count | 3 | 100% | 100.0% | 100.0% | 38.69 | 14.17 |
| ifc_models / length | 2 | 100% | 100.0% | 100.0% | 118.67 | 26.14 |
| **ALL** | 38 | 100% | 100.0% | 100.0% | 41.74 | 14.37 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| nl | 21 | 100% | 100.0% | 100.0% | 40.07 | 14.83 |
| en | 17 | 100% | 100.0% | 100.0% | 43.81 | 13.80 |
| **ALL** | 38 | 100% | 100.0% | 100.0% | 41.74 | 14.37 |
