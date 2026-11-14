# vlm_q3vl8b_r3_test1000

model `Qwen/Qwen3-VL-8B-Instruct` + LoRA, test split, n=1000 (question ids of `vlm_q3vl8b_r2_test1000.jsonl`), 1000 answered; cost = 10 min GPU wall time x $5.19/h

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| cubicasa5k | 500 | 100% | 73.8% | 73.8% | 0.87 | 1.40 |
| swiss_dwellings | 500 | 100% | 72.2% | 72.2% | 0.87 | 2.91 |
| **ALL** | 1000 | 100% | 73.0% | 73.0% | 0.87 | 2.15 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 500 | 100% | 71.8% | 71.8% | 0.87 | 2.23 |
| fi | 250 | 100% | 76.8% | 76.8% | 0.87 | 1.31 |
| de | 191 | 100% | 72.3% | 72.3% | 0.87 | 2.88 |
| fr | 40 | 100% | 70.0% | 70.0% | 0.87 | 2.84 |
| it | 19 | 100% | 68.4% | 68.4% | 0.87 | 2.28 |
| **ALL** | 1000 | 100% | 73.0% | 73.0% | 0.87 | 2.15 |
