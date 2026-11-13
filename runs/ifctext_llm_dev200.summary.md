# ifctext_llm_dev200

solver `ifctext@llm`, split `dev`, n=200, stratified sample 200, text scored by LLM judge (judge cost $0.101, not in $/1k q)

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| text | 200 | 100% | 49.0% | 49.0% | 2.28 | 14.54 |
| **ALL** | 200 | 100% | 49.0% | 49.0% | 2.28 | 14.54 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_bench | 200 | 100% | 49.0% | 49.0% | 2.28 | 14.54 |
| **ALL** | 200 | 100% | 49.0% | 49.0% | 2.28 | 14.54 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_bench / text | 200 | 100% | 49.0% | 49.0% | 2.28 | 14.54 |
| **ALL** | 200 | 100% | 49.0% | 49.0% | 2.28 | 14.54 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 195 | 100% | 49.2% | 49.2% | 2.30 | 14.61 |
| et | 2 | 100% | 50.0% | 50.0% | 1.27 | 11.94 |
| fr | 2 | 100% | 50.0% | 50.0% | 1.59 | 11.61 |
| nl | 1 | 100% | 0.0% | 0.0% | 1.44 | 11.99 |
| **ALL** | 200 | 100% | 49.0% | 49.0% | 2.28 | 14.54 |
