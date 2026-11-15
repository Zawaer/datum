# router_full_all_v8_r7

solver `router`, split `all`, n=8756, questions of `cache/full_all/router_full_all_v8/ids_g1.jsonl`, text scored by LLM judge (judge cost $0.000, not in $/1k q)

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| count | 7434 | 100% | 90.1% | 90.1% | 0.00 | 0.05 |
| area | 1186 | 100% | 100.0% | 100.0% | 0.00 | 0.00 |
| text | 120 | 100% | 63.3% | 63.3% | 2.52 | 0.06 |
| volume | 10 | 100% | 100.0% | 100.0% | 0.00 | 0.00 |
| length | 6 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| **ALL** | 8756 | 100% | 91.1% | 91.1% | 0.03 | 0.05 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| cubicasa5k | 5265 | 100% | 86.0% | 86.0% | 0.00 | 0.07 |
| swiss_dwellings | 3118 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| ifc_models | 253 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| ifc_bench | 120 | 100% | 63.3% | 63.3% | 2.52 | 0.06 |
| **ALL** | 8756 | 100% | 91.1% | 91.1% | 0.03 | 0.05 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| cubicasa5k / count | 5265 | 100% | 86.0% | 86.0% | 0.00 | 0.07 |
| swiss_dwellings / count | 2120 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| swiss_dwellings / area | 998 | 100% | 100.0% | 100.0% | 0.00 | 0.00 |
| ifc_models / area | 188 | 100% | 100.0% | 100.0% | 0.00 | 0.00 |
| ifc_bench / text | 120 | 100% | 63.3% | 63.3% | 2.52 | 0.06 |
| ifc_models / count | 49 | 100% | 100.0% | 100.0% | 0.00 | 0.02 |
| ifc_models / volume | 10 | 100% | 100.0% | 100.0% | 0.00 | 0.00 |
| ifc_models / length | 6 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| **ALL** | 8756 | 100% | 91.1% | 91.1% | 0.03 | 0.05 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 4438 | 100% | 90.7% | 90.7% | 0.07 | 0.06 |
| fi | 2633 | 100% | 86.0% | 86.0% | 0.00 | 0.05 |
| de | 1111 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| fr | 316 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| it | 188 | 100% | 100.0% | 100.0% | 0.00 | 0.00 |
| et | 58 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| pl | 11 | 100% | 100.0% | 100.0% | 0.00 | 0.00 |
| es | 1 | 100% | 100.0% | 100.0% | 0.00 | 0.02 |
| **ALL** | 8756 | 100% | 91.1% | 91.1% | 0.03 | 0.05 |
