# ifctext_llm_dev200

solver `ifctext@llm`, split `dev`, n=200, stratified sample 200, text scored by LLM judge (judge cost $0.095, not in $/1k q)

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| text | 200 | 100% | 50.0% | 50.0% | 2.25 | 19.27 |
| **ALL** | 200 | 100% | 50.0% | 50.0% | 2.25 | 19.27 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_bench | 200 | 100% | 50.0% | 50.0% | 2.25 | 19.27 |
| **ALL** | 200 | 100% | 50.0% | 50.0% | 2.25 | 19.27 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_bench / text | 200 | 100% | 50.0% | 50.0% | 2.25 | 19.27 |
| **ALL** | 200 | 100% | 50.0% | 50.0% | 2.25 | 19.27 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 199 | 100% | 49.7% | 49.7% | 2.25 | 19.25 |
| fr | 1 | 100% | 100.0% | 100.0% | 1.83 | 23.21 |
| **ALL** | 200 | 100% | 50.0% | 50.0% | 2.25 | 19.27 |
