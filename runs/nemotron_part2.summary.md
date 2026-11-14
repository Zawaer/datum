# nemotron_part2

solver `nemotron`, split `test`, n=281

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| area | 108 | 81% | 8.3% | 10.3% | 4.16 | 66.47 |
| count | 99 | 90% | 53.5% | 59.6% | 2.53 | 37.34 |
| volume | 52 | 81% | 1.9% | 2.4% | 4.52 | 67.71 |
| length | 22 | 55% | 0.0% | 0.0% | 6.90 | 102.05 |
| **ALL** | 281 | 82% | 22.4% | 27.4% | 3.86 | 59.22 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_models | 173 | 81% | 8.1% | 10.0% | 3.82 | 54.53 |
| swiss_dwellings | 108 | 83% | 45.4% | 54.4% | 3.94 | 66.73 |
| **ALL** | 281 | 82% | 22.4% | 27.4% | 3.86 | 59.22 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_models / area | 54 | 93% | 1.9% | 2.0% | 2.60 | 32.89 |
| swiss_dwellings / count | 54 | 98% | 75.9% | 77.4% | 2.16 | 33.42 |
| swiss_dwellings / area | 54 | 69% | 14.8% | 21.6% | 5.71 | 100.05 |
| ifc_models / volume | 52 | 81% | 1.9% | 2.4% | 4.52 | 67.71 |
| ifc_models / count | 45 | 80% | 26.7% | 33.3% | 2.97 | 42.04 |
| ifc_models / length | 22 | 55% | 0.0% | 0.0% | 6.90 | 102.05 |
| **ALL** | 281 | 82% | 22.4% | 27.4% | 3.86 | 59.22 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 136 | 82% | 20.6% | 25.2% | 3.97 | 59.02 |
| de | 70 | 71% | 27.1% | 38.0% | 4.46 | 74.01 |
| nl | 49 | 90% | 4.1% | 4.5% | 3.20 | 42.50 |
| fr | 16 | 94% | 62.5% | 66.7% | 3.10 | 53.56 |
| it | 10 | 100% | 40.0% | 40.0% | 2.70 | 49.38 |
| **ALL** | 281 | 82% | 22.4% | 27.4% | 3.86 | 59.22 |
