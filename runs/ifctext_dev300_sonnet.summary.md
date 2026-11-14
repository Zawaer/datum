# ifctext_dev300_sonnet

solver `ifctext@route-sonnet`, split `dev`, n=300, stratified sample 300, text scored by LLM judge (judge cost $0.098, not in $/1k q)

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| text | 300 | 100% | 59.3% | 59.3% | 23.91 | 4.02 |
| **ALL** | 300 | 100% | 59.3% | 59.3% | 23.91 | 4.02 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_bench | 300 | 100% | 59.3% | 59.3% | 23.91 | 4.02 |
| **ALL** | 300 | 100% | 59.3% | 59.3% | 23.91 | 4.02 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_bench / text | 300 | 100% | 59.3% | 59.3% | 23.91 | 4.02 |
| **ALL** | 300 | 100% | 59.3% | 59.3% | 23.91 | 4.02 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 297 | 100% | 58.9% | 58.9% | 23.97 | 4.05 |
| ? | 1 | 100% | 100.0% | 100.0% | 26.12 | 0.51 |
| pl | 1 | 100% | 100.0% | 100.0% | 13.48 | 0.53 |
| fr | 1 | 100% | 100.0% | 100.0% | 13.09 | 2.76 |
| **ALL** | 300 | 100% | 59.3% | 59.3% | 23.91 | 4.02 |
