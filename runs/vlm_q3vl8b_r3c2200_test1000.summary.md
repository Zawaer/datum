# vlm_q3vl8b_r3c2200_test1000

model `Qwen/Qwen3-VL-8B-Instruct` + LoRA, test split, n=1000 (question ids of `vlm_q3vl8b_r2_test1000.jsonl`), 1000 answered; cost = 30 min GPU wall time x $5.19/h

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| cubicasa5k | 500 | 100% | 74.4% | 74.4% | 2.59 | 1.06 |
| swiss_dwellings | 500 | 100% | 71.6% | 71.6% | 2.59 | 2.31 |
| **ALL** | 1000 | 100% | 73.0% | 73.0% | 2.59 | 1.68 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 500 | 100% | 73.2% | 73.2% | 2.59 | 1.76 |
| fi | 250 | 100% | 75.2% | 75.2% | 2.59 | 1.02 |
| de | 191 | 100% | 71.2% | 71.2% | 2.59 | 2.26 |
| fr | 40 | 100% | 70.0% | 70.0% | 2.59 | 1.96 |
| it | 19 | 100% | 63.2% | 63.2% | 2.59 | 1.90 |
| **ALL** | 1000 | 100% | 73.0% | 73.0% | 2.59 | 1.68 |
