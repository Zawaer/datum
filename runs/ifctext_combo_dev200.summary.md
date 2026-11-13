# ifctext_combo_dev200

solver `ifctext@combo`, split `dev`, n=200, stratified sample 200, text scored by LLM judge (judge cost $0.063, not in $/1k q)

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| text | 200 | 100% | 47.0% | 47.0% | 2.36 | 20.70 |
| **ALL** | 200 | 100% | 47.0% | 47.0% | 2.36 | 20.70 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_bench | 200 | 100% | 47.0% | 47.0% | 2.36 | 20.70 |
| **ALL** | 200 | 100% | 47.0% | 47.0% | 2.36 | 20.70 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_bench / text | 200 | 100% | 47.0% | 47.0% | 2.36 | 20.70 |
| **ALL** | 200 | 100% | 47.0% | 47.0% | 2.36 | 20.70 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 199 | 100% | 46.7% | 46.7% | 2.37 | 20.70 |
| fr | 1 | 100% | 100.0% | 100.0% | 1.67 | 20.16 |
| **ALL** | 200 | 100% | 47.0% | 47.0% | 2.36 | 20.70 |
