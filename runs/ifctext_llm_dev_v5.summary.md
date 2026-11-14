# ifctext_llm_dev_v5

solver `ifctext@llm`, split `dev`, n=710, text scored by LLM judge (judge cost $0.361, not in $/1k q)

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| text | 710 | 100% | 56.3% | 56.3% | 2.75 | 6.40 |
| **ALL** | 710 | 100% | 56.3% | 56.3% | 2.75 | 6.40 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_bench | 710 | 100% | 56.3% | 56.3% | 2.75 | 6.40 |
| **ALL** | 710 | 100% | 56.3% | 56.3% | 2.75 | 6.40 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_bench / text | 710 | 100% | 56.3% | 56.3% | 2.75 | 6.40 |
| **ALL** | 710 | 100% | 56.3% | 56.3% | 2.75 | 6.40 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 709 | 100% | 56.4% | 56.4% | 2.75 | 6.40 |
| fr | 1 | 100% | 0.0% | 0.0% | 1.91 | 5.05 |
| **ALL** | 710 | 100% | 56.3% | 56.3% | 2.75 | 6.40 |
