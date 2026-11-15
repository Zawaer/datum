# router_full_all_v8_s1

solver `router`, split `all`, n=31793, questions of `cache/full_all/router_full_all_v8/ids_1.jsonl`, text scored by LLM judge (judge cost $0.000, not in $/1k q)

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| count | 27967 | 100% | 90.2% | 90.2% | 0.00 | 0.09 |
| area | 3600 | 100% | 100.0% | 100.0% | 0.00 | 0.02 |
| text | 172 | 100% | 57.6% | 57.6% | 2.83 | 1.09 |
| volume | 36 | 100% | 100.0% | 100.0% | 0.00 | 0.02 |
| length | 18 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| **ALL** | 31793 | 100% | 91.1% | 91.1% | 0.02 | 0.09 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| cubicasa5k | 21390 | 100% | 87.1% | 87.1% | 0.00 | 0.10 |
| swiss_dwellings | 9450 | 100% | 100.0% | 100.0% | 0.00 | 0.03 |
| ifc_models | 779 | 100% | 100.0% | 100.0% | 0.00 | 0.03 |
| ifc_bench | 171 | 100% | 57.9% | 57.9% | 2.83 | 0.32 |
| opening_design | 3 | 100% | 66.7% | 66.7% | 2.21 | 132.69 |
| **ALL** | 31793 | 100% | 91.1% | 91.1% | 0.02 | 0.09 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| cubicasa5k / count | 21390 | 100% | 87.1% | 87.1% | 0.00 | 0.10 |
| swiss_dwellings / count | 6436 | 100% | 100.0% | 100.0% | 0.00 | 0.03 |
| swiss_dwellings / area | 3014 | 100% | 100.0% | 100.0% | 0.00 | 0.02 |
| ifc_models / area | 586 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| ifc_bench / text | 171 | 100% | 57.9% | 57.9% | 2.83 | 0.32 |
| ifc_models / count | 139 | 100% | 100.0% | 100.0% | 0.00 | 0.12 |
| ifc_models / volume | 36 | 100% | 100.0% | 100.0% | 0.00 | 0.02 |
| ifc_models / length | 18 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| opening_design / count | 2 | 100% | 100.0% | 100.0% | 2.13 | 132.08 |
| opening_design / text | 1 | 100% | 0.0% | 0.0% | 2.36 | 133.91 |
| **ALL** | 31793 | 100% | 91.1% | 91.1% | 0.02 | 0.09 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 16120 | 100% | 91.0% | 91.0% | 0.03 | 0.11 |
| fi | 10687 | 100% | 87.2% | 87.2% | 0.00 | 0.09 |
| de | 3306 | 100% | 100.0% | 100.0% | 0.00 | 0.02 |
| fr | 1116 | 100% | 100.0% | 100.0% | 0.00 | 0.02 |
| it | 360 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| et | 70 | 100% | 97.1% | 97.1% | 0.00 | 0.02 |
| da | 52 | 100% | 100.0% | 100.0% | 0.00 | 0.03 |
| es | 43 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| pl | 17 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| nl | 11 | 100% | 100.0% | 100.0% | 0.00 | 0.03 |
| ? | 6 | 100% | 83.3% | 83.3% | 0.00 | 2.04 |
| af | 2 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| ro | 2 | 100% | 100.0% | 100.0% | 0.00 | 1.72 |
| no | 1 | 100% | 100.0% | 100.0% | 0.00 | 0.04 |
| **ALL** | 31793 | 100% | 91.1% | 91.1% | 0.02 | 0.09 |

**2 questions hit a solver error** (they count as abstains):

- 2 x `RuntimeError: CUDA error: CUBLAS_STATUS_ALLOC_FAILED when calling `cublasCreate(handle)``
