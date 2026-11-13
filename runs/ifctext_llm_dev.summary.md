# ifctext_llm_dev

solver `ifctext@llm`, split `dev`, n=710, text scored by LLM judge (judge cost $0.125, not in $/1k q)

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| text | 710 | 100% | 49.7% | 49.7% | 1.44 | 4.13 |
| **ALL** | 710 | 100% | 49.7% | 49.7% | 1.44 | 4.13 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_bench | 710 | 100% | 49.7% | 49.7% | 1.44 | 4.13 |
| **ALL** | 710 | 100% | 49.7% | 49.7% | 1.44 | 4.13 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_bench / text | 710 | 100% | 49.7% | 49.7% | 1.44 | 4.13 |
| **ALL** | 710 | 100% | 49.7% | 49.7% | 1.44 | 4.13 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 667 | 100% | 50.4% | 50.4% | 1.53 | 4.38 |
| et | 12 | 100% | 16.7% | 16.7% | 0.00 | 0.02 |
| ? | 11 | 100% | 54.5% | 54.5% | 0.00 | 0.30 |
| sq | 6 | 100% | 33.3% | 33.3% | 0.00 | 0.03 |
| nl | 5 | 100% | 40.0% | 40.0% | 0.00 | 0.03 |
| sv | 4 | 100% | 50.0% | 50.0% | 0.00 | 0.02 |
| pl | 3 | 100% | 33.3% | 33.3% | 0.00 | 0.03 |
| tl | 1 | 100% | 100.0% | 100.0% | 0.00 | 0.01 |
| fr | 1 | 100% | 100.0% | 100.0% | 0.00 | 0.00 |
| **ALL** | 710 | 100% | 49.7% | 49.7% | 1.44 | 4.13 |
