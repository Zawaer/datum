"""bp/data.py: the fixed held-out split is by whole drawing, deterministic and ~20 % test."""
import collections
import hashlib
import json

import pytest

from bp.data import drawing_key, load_questions, source_of, split_of


def test_source_and_key():
    assert source_of("data/swiss_dwellings/site1_bldg2_floor3.pdf") == "swiss_dwellings"
    assert drawing_key("data/swiss_dwellings/site1_bldg2_floor3.pdf") == "swiss_dwellings/site1_bldg2_floor3"
    # an IFC model and the plans rendered from it share one key
    assert (drawing_key("data/ifc_models/kit-fzk-haus_ac20-fzk-haus.ifc")
            == drawing_key("data/ifc_models/kit-fzk-haus_ac20-fzk-haus_plan-01-erdgeschoss.pdf"))
    # the source is part of the key: the same stem in two sources is two drawings
    assert drawing_key("data/a/x.png") != drawing_key("data/b/x.png")


def test_split_is_a_pure_function_of_the_drawing():
    # pinned: sha1("<source>/<stem>")[:8] / 0xFFFFFFFF < 0.2 -> test. If this changes, every published number moves.
    for p in ("data/cubicasa5k/colorful-10052.png", "data/swiss_dwellings/site3387_bldg5238_floor23498.pdf",
              "data/ifc_models/bsc-clinic_clinic-hvac.ifc"):
        h = int(hashlib.sha1(drawing_key(p).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        assert split_of(p) == ("test" if h < 0.2 else "dev")
        assert split_of(p) == split_of(p)


def test_known_test_drawings():
    # drawings the published test run (runs/router_full_test_v7) answered
    assert split_of("data/swiss_dwellings/site3387_bldg5238_floor23498.pdf") == "test"
    assert split_of("data/cubicasa5k/colorful-10266.png") == "test"
    assert split_of("data/ifc_models/kit-fzk-haus_ac20-fzk-haus_plan-01-erdgeschoss.pdf") == "test"


@pytest.mark.parametrize("i", range(40))
def test_all_formats_of_a_drawing_on_one_side(i):
    stem = f"data/swiss_dwellings/site{i}_bldg{i * 7}_floor{i * 13}"
    sides = {split_of(f"{stem}.{ext}") for ext in ("pdf", "dxf", "png", "jpg", "svg")}
    assert len(sides) == 1
    ifc = f"data/ifc_models/model-{i}"
    assert len({split_of(f"{ifc}.ifc"), split_of(f"{ifc}_plan-00-ground.pdf"), split_of(f"{ifc}_plan-02.pdf")}) == 1


def test_about_twenty_percent_test():
    keys = [f"data/cubicasa5k/colorful-{i}.png" for i in range(5000)]
    frac = sum(split_of(k) == "test" for k in keys) / len(keys)
    assert 0.18 < frac < 0.22


def test_test_frac_parameter():
    keys = [f"data/x/{i}.png" for i in range(2000)]
    assert all(split_of(k, 0.0) == "dev" for k in keys)
    assert all(split_of(k, 1.01) == "test" for k in keys)
    # growing the test fraction only moves drawings dev -> test
    assert {k for k in keys if split_of(k, 0.2) == "test"} <= {k for k in keys if split_of(k, 0.3) == "test"}


def test_load_questions_adds_fields(tmp_path):
    rows = [{"path": "data/swiss_dwellings/a.pdf", "question": "q1", "answer": 1, "type": "count"},
            {"path": "data/swiss_dwellings/a.dxf", "question": "q2", "answer": 2.5, "type": "area", "id": 99}]
    (tmp_path / "questions.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    qs = load_questions(tmp_path)
    assert [q["id"] for q in qs] == [0, 99]
    assert [q["ext"] for q in qs] == ["pdf", "dxf"]
    assert {q["source"] for q in qs} == {"swiss_dwellings"}
    assert qs[0]["split"] == qs[1]["split"]


@pytest.mark.data
def test_real_dataset_split():
    qs = load_questions()
    by = collections.defaultdict(set)
    for q in qs:
        by[drawing_key(q["path"])].add(q["split"])
    assert all(len(s) == 1 for s in by.values()), "a drawing straddles the split"
    test = sum(s == {"test"} for s in by.values()) / len(by)
    assert 0.17 < test < 0.23
    n_test = sum(q["split"] == "test" for q in qs)
    if len(qs) == 127_044:  # the full release: the README's headline test count
        assert n_test == 25_420
