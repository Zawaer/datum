# ifctext_dev_haiku_sheetfix

solver `ifctext`, split `dev`, n=710, text scored by LLM judge (judge cost $0.023, not in $/1k q)

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| text | 710 | 100% | 57.9% | 57.9% | 2.45 | 0.70 |
| **ALL** | 710 | 100% | 57.9% | 57.9% | 2.45 | 0.70 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_bench | 710 | 100% | 57.9% | 57.9% | 2.45 | 0.70 |
| **ALL** | 710 | 100% | 57.9% | 57.9% | 2.45 | 0.70 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_bench / text | 710 | 100% | 57.9% | 57.9% | 2.45 | 0.70 |
| **ALL** | 710 | 100% | 57.9% | 57.9% | 2.45 | 0.70 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 684 | 100% | 57.7% | 57.7% | 2.47 | 0.72 |
| nl | 17 | 100% | 64.7% | 64.7% | 1.69 | 0.06 |
| sq | 5 | 100% | 60.0% | 60.0% | 2.28 | 0.28 |
| fr | 2 | 100% | 0.0% | 0.0% | 1.69 | 0.07 |
| it | 1 | 100% | 100.0% | 100.0% | 3.09 | 0.11 |
| sv | 1 | 100% | 100.0% | 100.0% | 1.18 | 0.03 |
| **ALL** | 710 | 100% | 57.9% | 57.9% | 2.45 | 0.70 |
