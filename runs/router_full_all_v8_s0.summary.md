# router_full_all_v8_s0

solver `router`, split `all`, n=31840, questions of `cache/full_all/router_full_all_v8/ids_0.jsonl`, text scored by LLM judge (judge cost $0.000, not in $/1k q)

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| count | 28037 | 100% | 90.8% | 90.8% | 0.00 | 0.10 |
| area | 3562 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| text | 181 | 100% | 55.2% | 55.2% | 2.44 | 0.71 |
| volume | 40 | 100% | 100.0% | 100.0% | 0.00 | 0.04 |
| length | 20 | 100% | 100.0% | 100.0% | 0.00 | 0.05 |
| **ALL** | 31840 | 100% | 91.6% | 91.6% | 0.01 | 0.09 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| cubicasa5k | 21414 | 100% | 88.0% | 88.0% | 0.00 | 0.10 |
| swiss_dwellings | 9442 | 100% | 100.0% | 100.0% | 0.00 | 0.02 |
| ifc_models | 786 | 100% | 100.0% | 100.0% | 0.00 | 0.54 |
| ifc_bench | 178 | 100% | 54.5% | 54.5% | 2.46 | 0.68 |
| opening_design | 20 | 100% | 95.0% | 95.0% | 1.68 | 4.26 |
| **ALL** | 31840 | 100% | 91.6% | 91.6% | 0.01 | 0.09 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| cubicasa5k / count | 21414 | 100% | 88.0% | 88.0% | 0.00 | 0.10 |
| swiss_dwellings / count | 6442 | 100% | 100.0% | 100.0% | 0.00 | 0.03 |
| swiss_dwellings / area | 3000 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| ifc_models / area | 562 | 100% | 100.0% | 100.0% | 0.00 | 0.03 |
| ifc_bench / text | 178 | 100% | 54.5% | 54.5% | 2.46 | 0.68 |
| ifc_models / count | 164 | 100% | 100.0% | 100.0% | 0.00 | 2.45 |
| ifc_models / volume | 40 | 100% | 100.0% | 100.0% | 0.00 | 0.04 |
| ifc_models / length | 20 | 100% | 100.0% | 100.0% | 0.00 | 0.05 |
| opening_design / count | 17 | 100% | 94.1% | 94.1% | 1.70 | 4.61 |
| opening_design / text | 3 | 100% | 100.0% | 100.0% | 1.54 | 2.28 |
| **ALL** | 31840 | 100% | 91.6% | 91.6% | 0.01 | 0.09 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 16016 | 100% | 91.4% | 91.4% | 0.03 | 0.10 |
| fi | 10700 | 100% | 88.0% | 88.0% | 0.00 | 0.09 |
| de | 3223 | 100% | 100.0% | 100.0% | 0.00 | 0.06 |
| fr | 1035 | 100% | 100.0% | 100.0% | 0.00 | 0.03 |
| it | 538 | 100% | 100.0% | 100.0% | 0.00 | 0.03 |
| nl | 124 | 100% | 100.0% | 100.0% | 0.00 | 0.02 |
| et | 70 | 100% | 100.0% | 100.0% | 0.00 | 0.02 |
| es | 55 | 100% | 100.0% | 100.0% | 0.00 | 1.38 |
| da | 50 | 100% | 100.0% | 100.0% | 0.00 | 0.04 |
| pl | 9 | 100% | 100.0% | 100.0% | 0.00 | 0.02 |
| ro | 8 | 100% | 100.0% | 100.0% | 0.00 | 0.87 |
| af | 6 | 100% | 100.0% | 100.0% | 0.00 | 0.02 |
| ? | 5 | 100% | 100.0% | 100.0% | 0.00 | 2.47 |
| no | 1 | 100% | 100.0% | 100.0% | 0.00 | 0.03 |
| **ALL** | 31840 | 100% | 91.6% | 91.6% | 0.01 | 0.09 |

**2 questions hit a solver error** (they count as abstains):

- 1 x `RuntimeError: CUDA error: CUBLAS_STATUS_ALLOC_FAILED when calling `cublasCreate(handle)``
- 1 x `OutOfMemoryError: CUDA out of memory. Tried to allocate 100.00 MiB. GPU 0 has a total capacity of 7.62 GiB of which 31.6`
