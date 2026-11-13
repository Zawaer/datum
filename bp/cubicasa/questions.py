"""Map a cubicasa5k question (English or Finnish template) to the thing to count."""
import re

# (key, regex) in priority order: first match wins.
_RULES = [
    ("bathroom", r"bathrooms or washrooms|kylpy- tai pesuhuone"),
    ("wc_room", r"separate WC rooms|erillist\w* WC-tilaa"),
    ("toilet", r"toilet bowls|WC-istuin"),
    ("sink", r"sinks and wash basins|pesu- ja tiskiallas"),
    ("shower_bath", r"showers and bathtubs|suihkua ja kylpyamme"),
    ("door", r"How many doors|Kuinka monta ovea"),
    ("window", r"windows|ikkuna"),
    ("sauna", r"saunas?\b|saunaa"),
    ("kitchen", r"kitchens|keittiö"),
    ("bedroom", r"bedrooms|makuuhuone"),
    ("balcony", r"balcon|parveke"),
    ("floor", r"floors \(storeys\)|kerrosta"),
]

LABEL = {
    "wc_room": "WC room", "bathroom": "bathroom", "toilet": "toilet", "sink": "sink",
    "shower_bath": "shower/bathtub", "door": "door", "window": "window", "sauna": "sauna",
    "kitchen": "kitchen", "bedroom": "bedroom", "balcony": "balcony", "floor": "floor",
}


def target(question: str) -> str | None:
    for key, rx in _RULES:
        if re.search(rx, question, re.I):
            return key
    return None
