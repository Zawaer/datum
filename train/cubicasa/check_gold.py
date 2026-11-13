"""How were the gold counts defined? Compare candidate counting rules over the CubiCasa5k SVG
annotations with the gold answers, on DEV-split drawings only.

    .venv/bin/python train/cubicasa/check_gold.py <dir with <stem>.svg files>
"""
import collections
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from bp.cubicasa.questions import target  # noqa: E402
from bp.cubicasa.svg import parse  # noqa: E402
from bp.data import load_questions  # noqa: E402


def words(name):
    return [w for w in re.split(r"[^A-ZÅÄÖ0-9]+", name.upper()) if w]


def cands(objs):
    sp = [o for o in objs if o["cls"].startswith("Space")]
    ff = [o["cls"] for o in objs if o["cls"].startswith("FixedFurniture")]
    c = {}
    c["window"] = {"all": sum(o["cls"].startswith("Window") for o in objs)}
    doors = [o["cls"] for o in objs if o["cls"].startswith("Door")]
    c["door"] = {"all": len(doors), "no_none": sum("None" not in d for d in doors)}
    c["toilet"] = {"Toilet": sum(f.endswith(" Toilet") for f in ff)}
    c["sink"] = {"sinklike": sum("Sink" in f for f in ff)}
    c["shower_bath"] = {"shower+tub": sum(f.endswith(" Shower") or "Bathtub" in f for f in ff),
                        "+screens": sum("Shower" in f or "Bathtub" in f for f in ff)}
    c["floor"] = {"Floor": sum(o["cls"] == "Floor" for o in objs)}
    c["bedroom"] = {"cls": sum(o["cls"] == "Space Bedroom" for o in sp),
                    "nameMH": sum("MH" in words(o["name"]) for o in sp)}
    c["kitchen"] = {"cls": sum(o["cls"].startswith("Space Kitchen") for o in sp),
                    "name": sum(any(w in ("K", "KK", "KEITTIÖ", "TK", "AK") for w in words(o["name"])) for o in sp),
                    "cls|name": sum(o["cls"].startswith("Space Kitchen") or
                                    any(w in ("K", "KK", "KEITTIÖ") for w in words(o["name"])) for o in sp)}
    c["sauna"] = {"cls": sum(o["cls"] == "Space Sauna" for o in sp),
                  "name": sum(any(w in ("S", "SAUNA", "SAUNA") for w in words(o["name"])) for o in sp),
                  "stove": sum("SaunaStove" in f for f in ff),
                  "cls|name": sum(o["cls"] == "Space Sauna" or "S" in words(o["name"]) or "SAUNA" in words(o["name"])
                                  for o in sp)}
    c["wc_room"] = {"nameWC": sum(words(o["name"]) == ["WC"] for o in sp),
                    "nameWCany": sum("WC" in words(o["name"]) for o in sp)}
    bathw = ("KH", "KPH", "PH", "PESUH", "SH", "PSH", "PESU")
    c["bathroom"] = {"clsBath-notWC": sum(o["cls"].startswith("Space Bath") and words(o["name"]) != ["WC"] for o in sp),
                     "name": sum(any(w in bathw for w in words(o["name"])) for o in sp)}
    c["balcony"] = {"clsBalcony": sum(o["cls"] == "Space Outdoor Balcony" for o in sp),
                    "name": sum(any(w.startswith("PARVEKE") or w.startswith("LASITETTU") for w in words(o["name"]))
                                for o in sp),
                    "outdoor": sum(o["cls"].startswith("Space Outdoor") for o in sp)}
    # the rule the detector pipeline uses (bp/cubicasa/classes.py + solver post-processing)
    from bp.cubicasa.classes import COUNTS, svg_class
    lab = [(svg_class(o), o["bbox"]) for o in objs if o.get("bbox") is not None]
    for t, cl in COUNTS.items():
        kept = [x for x in lab if x[0] in cl]
        if t == "sauna":
            rooms = [b for n, b in kept if n == "sauna_room"]
            kept = [(n, b) for n, b in kept if n == "sauna_room" or not any(
                r[0] <= (b[0] + b[2]) / 2 <= r[2] and r[1] <= (b[1] + b[3]) / 2 <= r[3] for r in rooms)]
        c[t]["DETECTOR_RULE"] = len(kept)
    return c


def main(svg_dir):
    svg_dir = Path(svg_dir)
    qs = [q for q in load_questions() if q["source"] == "cubicasa5k" and q["split"] == "dev"
          and q["question"].startswith(("How", "What"))]
    stats = collections.defaultdict(lambda: collections.Counter())
    tot = collections.Counter()
    miss = collections.defaultdict(list)
    cache = {}
    for q in qs:
        stem = Path(q["path"]).stem
        f = svg_dir / f"{stem}.svg"
        if not f.exists() or f.stat().st_size == 0:
            continue
        if stem not in cache:
            cache[stem] = cands(parse(f)["objects"])
        t = target(q["question"])
        tot[t] += 1
        for k, v in cache[stem][t].items():
            if v == round(float(q["answer"])):
                stats[t][k] += 1
            else:
                miss[(t, k)].append((stem, v, q["answer"]))
    for t in tot:
        print(t, tot[t], {k: f"{v / tot[t]:.0%}" for k, v in stats[t].items()})
    for k, v in miss.items():
        print(k, v[:6])


if __name__ == "__main__":
    main(sys.argv[1])
