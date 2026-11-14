"""Rows for the VLM second opinion on every cubicasa DEV question of the YOLO-validation drawings (the drawings
neither the detector nor the VLM trained on; same md5 rule in make_yolo.py and build_dataset.py), in the
eval_vlm.py row format, with images prepared for the model.

    .venv/bin/python train/vlm/make_dev_rows.py   -> cache/vlm_dev/devval_cc.jsonl, cache/vlm_dev/img/
Then on the GPU box: eval_vlm.py --data cache/vlm_dev --file devval_cc.jsonl --in-order --n 100000 (vLLM).
"""
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "train/vlm"))
from build_dataset import is_val, lang_of  # noqa: E402
from bp.cubicasa.questions import target  # noqa: E402
from bp.data import data_root, load_questions  # noqa: E402
from bp.vlm.format import budget_for, prepare_image  # noqa: E402

Image.MAX_IMAGE_PIXELS = None


def main():
    out = ROOT / "cache/vlm_dev"
    val = {p.stem for p in (ROOT / "cache/yolo_cc/images/val").glob("*.png")}
    rows = []
    for q in load_questions():
        st = Path(q["path"]).stem
        if q["source"] != "cubicasa5k" or q["split"] != "dev" or st not in val:
            continue
        assert is_val(st)
        img = out / "img/cubicasa5k" / f"{st}.png"
        if not img.exists():
            img.parent.mkdir(parents=True, exist_ok=True)
            prepare_image(Image.open(data_root() / q["path"]), budget_for("cubicasa5k")).save(img, compress_level=3)
        rows.append({"id": q["id"], "image": f"img/cubicasa5k/{st}.png", "question": q["question"],
                     "gold": q["answer"], "source": "cubicasa5k", "target": target(q["question"]) or "?",
                     "lang": lang_of(q["question"]), "path": q["path"], "answer": None, "split": "dev"})
    with open(out / "devval_cc.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(len(rows), "rows,", len({r["path"] for r in rows}), "drawings")


if __name__ == "__main__":
    main()
