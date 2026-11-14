# router_full_test_v6

solver `router`, split `test`, n=25420, text scored by LLM judge (judge cost $0.000, not in $/1k q)

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| count | 22212 | 100% | 88.3% | 88.3% | 0.00 | 0.03 |
| area | 3024 | 100% | 99.9% | 99.9% | 0.00 | 0.01 |
| text | 110 | 100% | 38.2% | 38.2% | 3.06 | 2.37 |
| volume | 52 | 100% | 100.0% | 100.0% | 0.00 | 0.02 |
| length | 22 | 100% | 100.0% | 100.0% | 0.00 | 0.03 |
| **ALL** | 25420 | 100% | 89.5% | 89.5% | 0.01 | 0.04 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| cubicasa5k | 16496 | 100% | 84.2% | 84.2% | 0.00 | 0.04 |
| swiss_dwellings | 8214 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| ifc_models | 600 | 100% | 100.0% | 100.0% | 0.00 | 0.03 |
| ifc_bench | 110 | 100% | 38.2% | 38.2% | 3.06 | 2.37 |
| **ALL** | 25420 | 100% | 89.5% | 89.5% | 0.01 | 0.04 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| cubicasa5k / count | 16496 | 100% | 84.2% | 84.2% | 0.00 | 0.04 |
| swiss_dwellings / count | 5580 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| swiss_dwellings / area | 2634 | 100% | 99.9% | 99.9% | 0.00 | 0.01 |
| ifc_models / area | 390 | 100% | 100.0% | 100.0% | 0.00 | 0.02 |
| ifc_models / count | 136 | 100% | 100.0% | 100.0% | 0.00 | 0.07 |
| ifc_bench / text | 110 | 100% | 38.2% | 38.2% | 3.06 | 2.37 |
| ifc_models / volume | 52 | 100% | 100.0% | 100.0% | 0.00 | 0.02 |
| ifc_models / length | 22 | 100% | 100.0% | 100.0% | 0.00 | 0.03 |
| **ALL** | 25420 | 100% | 89.5% | 89.5% | 0.01 | 0.04 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 12762 | 100% | 89.2% | 89.2% | 0.03 | 0.05 |
| fi | 8245 | 100% | 84.2% | 84.2% | 0.00 | 0.03 |
| de | 2917 | 100% | 99.9% | 99.9% | 0.00 | 0.01 |
| fr | 882 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| it | 390 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| nl | 217 | 100% | 100.0% | 100.0% | 0.00 | 0.02 |
| et | 5 | 100% | 100.0% | 100.0% | 0.00 | 2.11 |
| pl | 2 | 100% | 100.0% | 100.0% | 0.00 | 3.52 |
| **ALL** | 25420 | 100% | 89.5% | 89.5% | 0.01 | 0.04 |
