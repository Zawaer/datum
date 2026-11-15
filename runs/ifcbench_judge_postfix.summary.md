# ifcbench_judge_postfix

solver `router`, split `test`, n=110, text scored by LLM judge (judge cost $0.000, not in $/1k q)

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| text | 110 | 100% | 38.2% | 38.2% | 3.06 | 1.85 |
| **ALL** | 110 | 100% | 38.2% | 38.2% | 3.06 | 1.85 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_bench | 110 | 100% | 38.2% | 38.2% | 3.06 | 1.85 |
| **ALL** | 110 | 100% | 38.2% | 38.2% | 3.06 | 1.85 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_bench / text | 110 | 100% | 38.2% | 38.2% | 3.06 | 1.85 |
| **ALL** | 110 | 100% | 38.2% | 38.2% | 3.06 | 1.85 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 97 | 100% | 38.1% | 38.1% | 3.41 | 2.08 |
| ? | 6 | 100% | 33.3% | 33.3% | 0.00 | 0.16 |
| nl | 3 | 100% | 66.7% | 66.7% | 1.86 | 0.27 |
| pl | 2 | 100% | 0.0% | 0.0% | 0.00 | 0.01 |
| et | 2 | 100% | 50.0% | 50.0% | 0.00 | 0.01 |
| **ALL** | 110 | 100% | 38.2% | 38.2% | 3.06 | 1.85 |
