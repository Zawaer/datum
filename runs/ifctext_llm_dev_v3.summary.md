# ifctext_llm_dev

solver `ifctext@llm`, split `dev`, n=710, text scored by LLM judge (judge cost $0.245, not in $/1k q)

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| text | 710 | 100% | 47.3% | 47.3% | 1.59 | 10.47 |
| **ALL** | 710 | 100% | 47.3% | 47.3% | 1.59 | 10.47 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_bench | 710 | 100% | 47.3% | 47.3% | 1.59 | 10.47 |
| **ALL** | 710 | 100% | 47.3% | 47.3% | 1.59 | 10.47 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_bench / text | 710 | 100% | 47.3% | 47.3% | 1.59 | 10.47 |
| **ALL** | 710 | 100% | 47.3% | 47.3% | 1.59 | 10.47 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 707 | 100% | 47.2% | 47.2% | 1.60 | 10.52 |
| ? | 2 | 100% | 50.0% | 50.0% | 0.00 | 0.30 |
| fr | 1 | 100% | 100.0% | 100.0% | 0.00 | 0.00 |
| **ALL** | 710 | 100% | 47.3% | 47.3% | 1.59 | 10.47 |
