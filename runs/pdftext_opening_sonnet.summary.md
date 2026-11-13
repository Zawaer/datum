# pdftext_opening_sonnet

solver `ifctext@llm-sonnet`, split `all`, n=16, text scored by LLM judge (judge cost $0.005, not in $/1k q)

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| text | 16 | 100% | 93.8% | 93.8% | 56.80 | 12.92 |
| **ALL** | 16 | 100% | 93.8% | 93.8% | 56.80 | 12.92 |

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| opening_design | 16 | 100% | 93.8% | 93.8% | 56.80 | 12.92 |
| **ALL** | 16 | 100% | 93.8% | 93.8% | 56.80 | 12.92 |

## By source and type
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| opening_design / text | 16 | 100% | 93.8% | 93.8% | 56.80 | 12.92 |
| **ALL** | 16 | 100% | 93.8% | 93.8% | 56.80 | 12.92 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 16 | 100% | 93.8% | 93.8% | 56.80 | 12.92 |
| **ALL** | 16 | 100% | 93.8% | 93.8% | 56.80 | 12.92 |
