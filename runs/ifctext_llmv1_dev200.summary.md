# ifctext_llm_dev200

solver `ifctext@llm`, split `dev`, n=200, stratified sample 200, text scored by LLM judge (judge cost $0.091, not in $/1k q)

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| text | 200 | 100% | 46.5% | 46.5% | 2.20 | 18.71 |
| **ALL** | 200 | 100% | 46.5% | 46.5% | 2.20 | 18.71 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_bench | 200 | 100% | 46.5% | 46.5% | 2.20 | 18.71 |
| **ALL** | 200 | 100% | 46.5% | 46.5% | 2.20 | 18.71 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_bench / text | 200 | 100% | 46.5% | 46.5% | 2.20 | 18.71 |
| **ALL** | 200 | 100% | 46.5% | 46.5% | 2.20 | 18.71 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 196 | 100% | 46.4% | 46.4% | 2.21 | 18.70 |
| nl | 2 | 100% | 0.0% | 0.0% | 2.27 | 16.46 |
| et | 1 | 100% | 100.0% | 100.0% | 0.96 | 16.36 |
| fr | 1 | 100% | 100.0% | 100.0% | 1.55 | 27.95 |
| **ALL** | 200 | 100% | 46.5% | 46.5% | 2.20 | 18.71 |
