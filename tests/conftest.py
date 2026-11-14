"""Shared test setup.

The core suite needs no dataset, no detector weights and no API keys. Tests that do are marked
`@pytest.mark.data` and skip themselves when data/ (or the CubiCasa weights) is missing; CI runs
`pytest -m "not data"`.
"""
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
os.chdir(REPO)  # the code resolves data/, cache/ and runs/ relative to the repository root

FULL_DATA = REPO / "data/full/junction-dataset"
HAS_DATA = bool(os.environ.get("BP_DATA")) or (FULL_DATA / "questions.jsonl").exists()
WEIGHTS = Path(os.environ.get("CUBICASA_WEIGHTS", REPO / "cache/cubicasa/weights/best.pt"))
HAS_WEIGHTS = WEIGHTS.exists()

if not HAS_DATA:
    # app/server.py loads questions.jsonl at import: give it a four-line stand-in so the endpoints can be smoke-tested
    os.environ["BP_DATA"] = str(REPO / "tests/fixtures/mini_dataset")

# never spend money or wait on a model CLI from a test
os.environ.setdefault("BP_NORMALIZE", "0")
os.environ.setdefault("BP_CROSSCHECK", "0")


def pytest_collection_modifyitems(config, items):
    skip_data = pytest.mark.skip(reason="dataset not found (data/full/junction-dataset or BP_DATA)")
    skip_w = pytest.mark.skip(reason="CubiCasa weights not found (cache/cubicasa/weights/best.pt)")
    for item in items:
        if "data" not in item.keywords:
            continue
        if not HAS_DATA:
            item.add_marker(skip_data)
        elif "weights" in item.keywords and not HAS_WEIGHTS:
            item.add_marker(skip_w)
