# ifctext_dev_haiku_rerun

solver `ifctext`, split `dev`, n=710, text scored by LLM judge (judge cost $0.000, not in $/1k q)

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| text | 710 | 100% | 57.0% | 57.0% | 2.51 | 0.36 |
| **ALL** | 710 | 100% | 57.0% | 57.0% | 2.51 | 0.36 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_bench | 710 | 100% | 57.0% | 57.0% | 2.51 | 0.36 |
| **ALL** | 710 | 100% | 57.0% | 57.0% | 2.51 | 0.36 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_bench / text | 710 | 100% | 57.0% | 57.0% | 2.51 | 0.36 |
| **ALL** | 710 | 100% | 57.0% | 57.0% | 2.51 | 0.36 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 671 | 100% | 57.5% | 57.5% | 2.55 | 0.37 |
| nl | 25 | 100% | 48.0% | 48.0% | 1.89 | 0.08 |
| sq | 5 | 100% | 60.0% | 60.0% | 2.05 | 0.38 |
| fr | 5 | 100% | 20.0% | 20.0% | 2.10 | 0.07 |
| it | 2 | 100% | 50.0% | 50.0% | 2.77 | 0.11 |
| et | 1 | 100% | 100.0% | 100.0% | 1.65 | 0.41 |
| sv | 1 | 100% | 100.0% | 100.0% | 1.18 | 0.05 |
| **ALL** | 710 | 100% | 57.0% | 57.0% | 2.51 | 0.36 |
