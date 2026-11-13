#!/usr/bin/env bash
# Rebuild every results artefact from runs/*.jsonl: judge verdicts for baseline text answers (cached, ~$0.03 the
# first time), tables (analysis/out), figures (docs/img/fig-*), docs/RESULTS.md.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
[ -f runs/prior_full_test.jsonl ] || $PY eval.py --solver prior --split test --name prior_full_test
$PY analysis/judge_runs.py $(ls runs/baseline_*.jsonl | grep -v judged | xargs -n1 basename | sed 's/\.jsonl$//')
cd analysis
../$PY tables.py
../$PY figures.py
../$PY report.py
