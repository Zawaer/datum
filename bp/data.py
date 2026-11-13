"""Dataset loading and the fixed held-out split.

The split is by *drawing*, not by question: every format of the same drawing
(same stem, different extension) and every language variant of a question land
in the same split, so nothing leaks from dev into test.
"""
import hashlib
import json
import os
from pathlib import Path

ROOTS = [
    os.environ.get("BP_DATA"),
    "data/full/junction-dataset",
    "data/preview/junction-dataset-preview",
]


def data_root() -> Path:
    for r in ROOTS:
        if r and (Path(r) / "questions.jsonl").exists():
            return Path(r)
    raise SystemExit("dataset not found; set BP_DATA to the folder holding questions.jsonl")


def source_of(path: str) -> str:
    return path.split("/")[1]


def drawing_key(path: str) -> str:
    """Group key shared by every format of one drawing (and IFC + its rendered plans)."""
    p = Path(path)
    # ifc_models/<model>_plan-<level>.pdf is rendered from <model>.ifc -> same group
    stem = p.stem.split("_plan-")[0]
    return f"{source_of(path)}/{stem}"


def split_of(path: str, test_frac: float = 0.2) -> str:
    key = drawing_key(path)
    h = int(hashlib.sha1(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "test" if h < test_frac else "dev"


def load_questions(root: Path | None = None):
    root = root or data_root()
    out = []
    with open(root / "questions.jsonl") as f:
        for i, line in enumerate(f):
            q = json.loads(line)
            q["id"] = i
            q["source"] = source_of(q["path"])
            q["ext"] = q["path"].rsplit(".", 1)[-1].lower()
            q["split"] = split_of(q["path"])
            out.append(q)
    return out
