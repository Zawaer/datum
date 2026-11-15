# router_full_all_v8_r6

solver `router`, split `all`, n=8643, questions of `cache/full_all/router_full_all_v8/ids_g0.jsonl`, text scored by LLM judge (judge cost $0.000, not in $/1k q)

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| count | 7338 | 100% | 90.2% | 90.2% | 0.00 | 0.05 |
| area | 1218 | 100% | 100.0% | 100.0% | 0.00 | 0.00 |
| text | 67 | 100% | 43.3% | 43.3% | 2.13 | 0.30 |
| volume | 14 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| length | 6 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| **ALL** | 8643 | 100% | 91.2% | 91.2% | 0.02 | 0.05 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| cubicasa5k | 5184 | 100% | 86.2% | 86.2% | 0.00 | 0.07 |
| swiss_dwellings | 3092 | 100% | 99.9% | 99.9% | 0.00 | 0.01 |
| ifc_models | 300 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| ifc_bench | 67 | 100% | 43.3% | 43.3% | 2.13 | 0.30 |
| **ALL** | 8643 | 100% | 91.2% | 91.2% | 0.02 | 0.05 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| cubicasa5k / count | 5184 | 100% | 86.2% | 86.2% | 0.00 | 0.07 |
| swiss_dwellings / count | 2092 | 100% | 99.9% | 99.9% | 0.00 | 0.01 |
| swiss_dwellings / area | 1000 | 100% | 100.0% | 100.0% | 0.00 | 0.00 |
| ifc_models / area | 218 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| ifc_bench / text | 67 | 100% | 43.3% | 43.3% | 2.13 | 0.30 |
| ifc_models / count | 62 | 100% | 100.0% | 100.0% | 0.00 | 0.04 |
| ifc_models / volume | 14 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| ifc_models / length | 6 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| **ALL** | 8643 | 100% | 91.2% | 91.2% | 0.02 | 0.05 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 4345 | 100% | 90.9% | 90.9% | 0.03 | 0.06 |
| fi | 2581 | 100% | 86.1% | 86.1% | 0.00 | 0.05 |
| de | 943 | 100% | 99.9% | 99.9% | 0.00 | 0.01 |
| fr | 490 | 100% | 100.0% | 100.0% | 0.00 | 0.00 |
| it | 138 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| et | 73 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| da | 27 | 100% | 100.0% | 100.0% | 0.00 | 0.02 |
| es | 21 | 100% | 100.0% | 100.0% | 0.00 | 0.00 |
| nl | 15 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| ? | 7 | 100% | 71.4% | 71.4% | 0.00 | 1.76 |
| pl | 3 | 100% | 100.0% | 100.0% | 0.00 | 0.00 |
| **ALL** | 8643 | 100% | 91.2% | 91.2% | 0.02 | 0.05 |
