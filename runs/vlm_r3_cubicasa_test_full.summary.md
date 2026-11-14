# vlm_r3_cubicasa_test_full

model `Qwen/Qwen3-VL-8B-Instruct` + LoRA r3 checkpoint-2200, test split, n=16496 (question ids of `cubicasa_test_v4.jsonl`), 16496 answered; cost = 31 min GPU wall time x $5.19/h

accuracy = correct / all questions (abstain counts as wrong); precision = correct / answered.

## By source
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| cubicasa5k | 16496 | 100% | 74.9% | 74.9% | 0.16 | 1.18 |
| **ALL** | 16496 | 100% | 74.9% | 74.9% | 0.16 | 1.18 |

## By language
| group | n | answered | accuracy | precision | $/1k q | s/q |
|---|---|---|---|---|---|---|
| en | 8248 | 100% | 74.9% | 74.9% | 0.16 | 1.18 |
| fi | 8247 | 100% | 75.0% | 75.0% | 0.16 | 1.18 |
| ? | 1 | 100% | 0.0% | 0.0% | 0.16 | 1.80 |
| **ALL** | 16496 | 100% | 74.9% | 74.9% | 0.16 | 1.18 |
