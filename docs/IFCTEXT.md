# IFC free-text route: does a stronger answering model help?

Experiment of 14.11.2026 on the **dev** split of `ifc_bench` (710 questions; 652 go to the LLM, the rest to
validated rules). Same fact sheet, same prompt, only the answering model changes. Judge: the usual Haiku judge.

## Why most dev failures are not a model-strength problem

Hand-labelled 40 judge-wrong dev answers (deterministic sample, `analysis/ifctext_failures.py`):

| cause | n / 40 |
|---|---|
| fact sheet lacks the information (truncated block, no cost / adjacency / parking / space area, missing element) | 13 |
| reference answer idiosyncratic or unreachable (estimates from outside the model, "not available" where the model has data, unit error in the reference, its own room categorisation) | 12 |
| model reasoning / interpretation (grouping, picking the wrong total, refusing an estimate, missed synonym) | 11 |
| judge too strict (extra correct detail, 0.9 % numeric difference, "none" vs "not available") | 4 |

Only about a quarter of the failures (~11 pp of dev) are reasoning errors a stronger model could fix.

## Sonnet 5.5 vs Haiku 5.5 (paired, 300-question stratified dev sample)

`eval.py --solver ifctext@route-sonnet --split dev --source ifc_bench --sample 300 --judge`

| answering model | accuracy (95 % CI) | $/question | median latency |
|---|---|---|---|
| Haiku (shipped) | 59.7 % (54.0-65.1) | $0.0026 | 3.5 s (fresh calls, full-dev run) |
| Sonnet | 59.3 % (53.7-64.7) | $0.0239 | 4.5 s |

Paired: **-0.3 pp** (bootstrap 95 % CI -4.0 to +3.3), Sonnet fixes 14 and breaks 15 (McNemar p = 1.0).
Sonnet costs ~9x as much per question for no measurable gain, so the default stays Haiku; Opus was not tried.
The model can be switched without code changes: `ifctext@route-sonnet` or `BP_IFCTEXT_MODEL=sonnet`.

## Fact-sheet fix (shipped)

City / campus models list every `IfcBuilding` with serialised complex properties (`Color={...}`), so the
195-building Ettenheim model overflowed the project block and the sheet showed 69 of 195. The project block now
skips serialised complex properties and, with 5+ entries, adds a count line and drops properties all entries share.
Full dev (710, Haiku): 57.0 % -> 57.9 %, +0.8 pp (CI +0.1 to +1.7; 7 fixed, 1 broken). The three Ettenheim fixes
are the intended effect; the other flips are on one model whose prompt changed slightly (resampling noise).
Below the +5 pp bar, so the test split was not re-run.

## Cost note

The Claude Code CLI writes a 1-hour prompt cache for every call (2x the input price) although each fact sheet is
used once. Setting `DISABLE_PROMPT_CACHING=1` for the CLI avoids the premium: Sonnet calls fell from ~$0.033 to
~$0.024 each in this experiment. Not applied to the shipped path (`bp/ifctext/llm.py`) yet.
