"""Detector classes and how CubiCasa5k SVG annotations map onto them.

The mapping follows what the gold answers were derived from (checked on dev drawings with
train/cubicasa/check_gold.py): windows = Window*, doors = Door* with a leaf, toilets = Toilet,
sinks = any *Sink*, showers+bathtubs = Shower + Bathtub, saunas = SaunaStove, rooms by Space class
(WC rooms are Space Bath labelled 'WC'), balconies = Space Outdoor Balcony, floors = Floor groups.
"""
import re

NAMES = ["window", "door", "doorway", "toilet", "sink", "shower", "bathtub", "sauna_stove",
         "bedroom", "kitchen", "bathroom", "wc_room", "balcony", "floor", "sauna_room"]
IDX = {n: i for i, n in enumerate(NAMES)}

# question target -> detector classes whose detections are counted
COUNTS = {
    "window": ["window"], "door": ["door"], "toilet": ["toilet"], "sink": ["sink"],
    "shower_bath": ["shower", "bathtub"], "sauna": ["sauna_stove"], "kitchen": ["kitchen"],
    "bedroom": ["bedroom"], "bathroom": ["bathroom"], "wc_room": ["wc_room"], "balcony": ["balcony"],
    "floor": ["floor"],
}


def _words(name):
    return [w for w in re.split(r"[^A-ZÅÄÖ0-9]+", (name or "").upper()) if w]


def svg_class(obj) -> str | None:
    """Detector class name of one parsed SVG object, or None to ignore it."""
    c = obj["cls"]
    if c == "Floor":
        return "floor"
    if c.startswith("Window"):
        return "window"
    if c.startswith("Door"):
        return "doorway" if c.split(" ")[1:2] == ["None"] else "door"
    if c.startswith("FixedFurniture"):
        if c.endswith(" Toilet"):
            return "toilet"
        if "Sink" in c:
            return "sink"
        if c.endswith(" Shower"):
            return "shower"
        if "Bathtub" in c:
            return "bathtub"
        if "SaunaStove" in c:
            return "sauna_stove"
        return None
    if c.startswith("Space"):
        if c == "Space Bedroom":
            return "bedroom"
        if c.startswith("Space Kitchen"):
            return "kitchen"
        if c.startswith("Space Bath"):
            return "wc_room" if _words(obj.get("name")) == ["WC"] else "bathroom"
        if c == "Space Outdoor Balcony":
            return "balcony"
        if c == "Space Sauna":
            return "sauna_room"
    return None
