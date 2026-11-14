# ifctext_route_test_v6

solver `ifctext`, split `test`, n=110, text scored by LLM judge (judge cost $0.055, not in $/1k q)

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| text | 110 | 100% | 38.2% | 38.2% | 3.06 | 6.93 |
| **ALL** | 110 | 100% | 38.2% | 38.2% | 3.06 | 6.93 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_bench | 110 | 100% | 38.2% | 38.2% | 3.06 | 6.93 |
| **ALL** | 110 | 100% | 38.2% | 38.2% | 3.06 | 6.93 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| ifc_bench / text | 110 | 100% | 38.2% | 38.2% | 3.06 | 6.93 |
| **ALL** | 110 | 100% | 38.2% | 38.2% | 3.06 | 6.93 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 99 | 100% | 38.4% | 38.4% | 3.40 | 7.68 |
| pl | 3 | 100% | 66.7% | 66.7% | 0.00 | 0.21 |
| ? | 3 | 100% | 0.0% | 0.0% | 0.00 | 0.20 |
| et | 2 | 100% | 50.0% | 50.0% | 0.00 | 0.06 |
| tl | 2 | 100% | 0.0% | 0.0% | 0.00 | 0.02 |
| nl | 1 | 100% | 100.0% | 100.0% | 0.00 | 0.19 |
| **ALL** | 110 | 100% | 38.2% | 38.2% | 3.06 | 6.93 |
