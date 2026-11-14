"""bp/vlm/gpu_power.py against deploy/vlm/power_stub.py (no real GPU, no network beyond 127.0.0.1)."""
import json
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from bp.vlm.gpu_power import GpuPower, _day_start

REPO = Path(__file__).resolve().parent.parent


def _load_stub():
    import importlib.util

    spec = importlib.util.spec_from_file_location("power_stub", REPO / "deploy/vlm/power_stub.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


stub_mod = _load_stub()


class Clock:
    def __init__(self, t=None):
        self.t = t if t is not None else _day_start(time.time()) + 10 * 3600  # 10:00 UTC today

    def __call__(self):
        return self.t


@pytest.fixture
def stub():
    srv = stub_mod.make_server(0, secret="s3cret", boot_s=0.3)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    srv.url = f"http://127.0.0.1:{srv.server_address[1]}"
    yield srv
    srv.shutdown()
    srv.server_close()


def stub_health(srv):
    def h():
        try:
            with urllib.request.urlopen(srv.url + "/v1/models", timeout=2) as r:
                return any(m["id"] == "bpvlm" for m in json.loads(r.read())["data"])
        except Exception:  # noqa: BLE001
            return False
    return h


def power(srv, tmp_path, **kw):
    kw.setdefault("health", stub_health(srv))
    return GpuPower(srv.url + "/hook", "s3cret", ledger=tmp_path / "gpu_power.jsonl", watch=False, **kw)


def wait_for(cond, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.02)
    return False


def starts(srv):
    return [c for c in srv.calls if c["action"] == "start"]


def test_no_hook_is_a_noop(tmp_path):
    pw = GpuPower("", "", ledger=tmp_path / "l.jsonl", health=lambda: True, watch=False)
    assert not pw.hooked
    assert pw.ensure_started() == "ready" and pw.state() == "ready"
    pw2 = GpuPower("", "", ledger=tmp_path / "l.jsonl", health=lambda: False, watch=False)
    assert pw2.ensure_started() == "off" and pw2.tick() is None
    assert not (tmp_path / "l.jsonl").exists()


def test_start_called_once(stub, tmp_path):
    pw = power(stub, tmp_path)
    assert pw.state() == "off"
    results = [pw.ensure_started() for _ in range(5)]
    assert results[0] == "starting"
    assert wait_for(lambda: not pw._starting)
    for _ in range(5):
        pw.ensure_started()
    assert len(starts(stub)) == 1
    ev = [json.loads(x)["event"] for x in (tmp_path / "gpu_power.jsonl").read_text().splitlines()]
    assert ev == ["start"]


def test_state_machine_off_starting_ready_off(stub, tmp_path):
    pw = power(stub, tmp_path, idle_min=0.0)
    assert pw.state() == "off"
    pw.ensure_started()
    assert pw.state() == "starting"
    assert wait_for(lambda: not pw._starting)
    assert 0 < pw.eta_s() <= 150
    assert wait_for(lambda: pw.state() == "ready", timeout=8)  # the stub's VLM answers 0.3 s after the start
    assert pw.eta_s() == 0
    pw._last_stop_try = -1e18
    assert pw.tick() is True  # idle 0 min -> stop
    assert stub.calls[-1]["action"] == "stop"
    assert pw.state() == "off"


def test_idle_stop_after_idle_minutes(stub, tmp_path):
    clk = Clock()
    pw = power(stub, tmp_path, idle_min=12, clock=clk)
    pw.ensure_started()
    assert wait_for(lambda: not pw._starting)
    clk.t += 11 * 60
    assert pw.tick() is None  # 11 idle minutes: still on
    pw.touch()                # a live ask
    clk.t += 11 * 60
    assert pw.tick() is None
    clk.t += 61
    assert pw.tick() is True  # 12+ idle minutes since the last use
    assert [c["action"] for c in stub.calls] == ["start", "stop"]
    rows = [json.loads(x) for x in (tmp_path / "gpu_power.jsonl").read_text().splitlines()]
    assert rows[-1]["event"] == "stop" and rows[-1]["reason"].startswith("idle")
    # 23 min 1 s billed at $2.89/h
    assert pw.spent_today() == pytest.approx((22 * 60 + 61) / 3600 * 2.89, rel=1e-6)


def test_budget_refusal(stub, tmp_path):
    clk = Clock()
    led = tmp_path / "gpu_power.jsonl"
    on = clk.t - 6 * 3600  # 6 h on today = $17.34 > $15
    led.write_text(json.dumps({"ts": on, "event": "start"}) + "\n" + json.dumps({"ts": clk.t - 60, "event": "stop"}) + "\n")
    pw = power(stub, tmp_path, clock=clk)
    assert pw.spent_today() > 15
    assert pw.ensure_started() == "refused"
    assert pw.ensure_started() == "refused"
    time.sleep(0.1)
    assert starts(stub) == []
    rows = [json.loads(x) for x in led.read_text().splitlines()]
    assert [r["event"] for r in rows].count("start_refused") == 1  # logged once, not per upload
    # a new UTC day resets the budget
    clk.t = _day_start(clk.t) + 86400 + 60
    assert pw.spent_today() == 0
    assert pw.ensure_started() == "starting"
    assert wait_for(lambda: len(starts(stub)) == 1)


def test_cap_reached_while_running_stops(stub, tmp_path):
    clk = Clock()
    pw = power(stub, tmp_path, cap_usd=1.0, clock=clk)
    pw.ensure_started()
    assert wait_for(lambda: not pw._starting)
    clk.t += 20 * 60  # $0.96
    pw.touch()
    assert pw.tick() is None
    clk.t += 2 * 60   # $1.06, in use but over the cap
    pw.touch()
    assert pw.tick() is True
    assert json.loads((tmp_path / "gpu_power.jsonl").read_text().splitlines()[-1])["reason"] == "daily cap"


def test_ledger_survives_restart(stub, tmp_path):
    clk = Clock()
    pw = power(stub, tmp_path, clock=clk)
    pw.ensure_started()
    assert wait_for(lambda: not pw._starting)
    clk.t += 3600
    pw2 = power(stub, tmp_path, clock=clk)  # the app restarted while the box was billed
    assert pw2.spent_today() == pytest.approx(2.89)
    assert pw2.ensure_started() in ("starting", "ready")
    time.sleep(0.1)
    assert len(starts(stub)) == 1  # it knows the box is on: no second start
    clk.t += 13 * 60
    assert pw2.tick() is True


def test_bad_secret_and_rate_limit(stub, tmp_path):
    pw = GpuPower(stub.url + "/hook", "wrong", ledger=tmp_path / "l.jsonl", health=lambda: False, watch=False)
    pw.ensure_started()
    assert wait_for(lambda: not pw._starting)
    assert pw.state() == "off" and pw.last_error == "HTTP 401"
    assert json.loads(Path(tmp_path / "l.jsonl").read_text().splitlines()[-1])["event"] == "start_failed"
    assert pw.ensure_started() == "off"  # within the 60 s cooldown: no new request
    assert stub.calls == []


# ---------------------------------------------------------------- app/server.py: /api/gpu and /api/upload_second
def test_server_upload_second_warming_to_ready(stub, tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from PIL import Image

    import app.server as S
    import bp.vlm.gpu_power as G

    monkeypatch.setenv("BP_VLM_URL", stub.url + "/v1")
    monkeypatch.setenv("BP_VLM_LIVE_TIMEOUT", "10")
    monkeypatch.setattr(G, "_power", power(stub, tmp_path, health=G._vlm_health))
    c = TestClient(S.app)
    assert c.get("/api/gpu").json()["state"] == "off"

    img = tmp_path / "plan.png"
    Image.new("RGB", (800, 600), "white").save(img)
    q = {"path": str(img), "question": "How many doors are there?", "type": "count", "source": "upload",
         "kind": "raster", "residential_plan": True}
    res = {"answer": 3, "method": "cubicasa-yolo", "confidence": 0.9,
           "crosscheck": {"status": "single", "second": None, "note": "no independent second reading"}}
    S._gpu_second_pending(res, q, "uploads/abc/plan.png")
    sp = res["second_pending"]
    assert sp["state"] == "starting" and sp["eta_s"] > 0
    assert c.get("/api/upload_second/" + sp["key"]).json()["status"] == "warming"
    g = c.get("/api/gpu").json()
    assert g["state"] in ("starting", "ready") and g["hooked"] and "spent_today" in g

    def poll():
        r = c.get("/api/upload_second/" + sp["key"]).json()
        poll.last = r
        return r["status"] == "ready"
    assert wait_for(poll, timeout=20), poll.last
    cc = poll.last["crosscheck"]
    assert cc["status"] == "agree" and cc["second"]["answer"] == 3  # the stub boxes 3 items
    assert all(e["file"].startswith("uploads/") or e["file"] == str(img) for e in cc["second"]["evidence"])
    assert len(starts(stub)) == 1
    assert c.get("/api/upload_second/0123456789abcdef").status_code == 404
    assert c.get("/api/upload_second/..%2f..").status_code == 404
