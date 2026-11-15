# router_full_all_v8_s2

solver `router`, split `all`, n=31898, questions of `cache/full_all/router_full_all_v8/ids_2.jsonl`, text scored by LLM judge (judge cost $0.002, not in $/1k q)

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| count | 28062 | 100% | 90.5% | 90.5% | 0.00 | 0.08 |
| area | 3611 | 100% | 99.9% | 99.9% | 0.00 | 0.01 |
| text | 183 | 100% | 48.1% | 48.1% | 2.51 | 3.25 |
| volume | 30 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| length | 12 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| **ALL** | 31898 | 100% | 91.4% | 91.4% | 0.02 | 0.09 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| cubicasa5k | 21484 | 100% | 87.6% | 87.6% | 0.00 | 0.10 |
| swiss_dwellings | 9382 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| ifc_models | 820 | 100% | 100.0% | 100.0% | 0.00 | 0.03 |
| ifc_bench | 171 | 100% | 45.0% | 45.0% | 2.56 | 3.19 |
| opening_design | 41 | 100% | 97.6% | 97.6% | 2.16 | 5.40 |
| **ALL** | 31898 | 100% | 91.4% | 91.4% | 0.02 | 0.09 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| cubicasa5k / count | 21484 | 100% | 87.6% | 87.6% | 0.00 | 0.10 |
| swiss_dwellings / count | 6376 | 100% | 100.0% | 100.0% | 0.00 | 0.02 |
| swiss_dwellings / area | 3006 | 100% | 99.9% | 99.9% | 0.00 | 0.00 |
| ifc_models / area | 596 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| ifc_models / count | 182 | 100% | 100.0% | 100.0% | 0.00 | 0.07 |
| ifc_bench / text | 171 | 100% | 45.0% | 45.0% | 2.56 | 3.19 |
| ifc_models / volume | 30 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| opening_design / count | 20 | 100% | 100.0% | 100.0% | 2.55 | 7.46 |
| ifc_models / length | 12 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| opening_design / text | 12 | 100% | 91.7% | 91.7% | 1.91 | 4.24 |
| opening_design / area | 9 | 100% | 100.0% | 100.0% | 1.62 | 2.35 |
| **ALL** | 31898 | 100% | 91.4% | 91.4% | 0.02 | 0.09 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 16070 | 100% | 91.1% | 91.1% | 0.03 | 0.12 |
| fi | 10736 | 100% | 87.7% | 87.7% | 0.00 | 0.09 |
| de | 3290 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| fr | 1126 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| it | 368 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| nl | 121 | 100% | 100.0% | 100.0% | 0.00 | 0.02 |
| et | 66 | 100% | 100.0% | 100.0% | 0.00 | 0.02 |
| es | 55 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| da | 46 | 100% | 100.0% | 100.0% | 0.00 | 0.03 |
| pl | 14 | 100% | 78.6% | 78.6% | 0.00 | 0.00 |
| ? | 4 | 100% | 75.0% | 75.0% | 0.00 | 3.00 |
| ro | 2 | 100% | 100.0% | 100.0% | 0.00 | 0.29 |
| **ALL** | 31898 | 100% | 91.4% | 91.4% | 0.02 | 0.09 |

**1 questions hit a solver error** (they count as abstains):

- 1 x `RuntimeError: cuDNN error: CUDNN_STATUS_INTERNAL_ERROR`
