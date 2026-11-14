"""The memory admission gate (bp/memgate.py) and its use for uploads (app/server.py): concurrent heavy jobs never hold
more than the budget together, the rest queue (FIFO) and say so through GET /api/queue, a job bigger than the budget
runs alone, nested holds on one thread don't deadlock, and parallel uploads of big synthetic sheets all succeed.
Big images are generated on the fly (mostly white: a few MB on disk) under tmp_path."""
import io
import threading
import time

import pytest

from bp import memgate as G

MB = 1 << 20


@pytest.fixture()
def small_budget(monkeypatch):
    monkeypatch.setattr(G, "BUDGET", 100 * MB)
    assert G.used() == 0 and not G._waiting


def _run_jobs(costs, hold_s=0.15):
    peak, cur, lock, order = [0], [0], threading.Lock(), []

    def job(i, c):
        with G.hold(c, tag=f"t{i}", label=f"job {i}"):
            with lock:
                cur[0] += min(c, G.BUDGET)
                peak[0] = max(peak[0], cur[0])
                order.append(i)
            time.sleep(hold_s)
            with lock:
                cur[0] -= min(c, G.BUDGET)

    ts = []
    for i, c in enumerate(costs):
        ts.append(threading.Thread(target=job, args=(i, c)))
        ts[-1].start()
        time.sleep(0.01)  # arrival order = index
    for t in ts:
        t.join(30)
    return peak[0], order


def test_concurrent_jobs_stay_within_budget(small_budget):
    peak, order = _run_jobs([40 * MB] * 8)
    assert peak <= 100 * MB  # two at a time
    assert sorted(order) == list(range(8))  # every job ran
    assert G.used() == 0


def test_fifo_and_oversize_runs_alone(small_budget):
    peak, order = _run_jobs([30 * MB, 500 * MB, 30 * MB, 30 * MB])
    assert order[:2] == [0, 1]  # the big one is not overtaken by the small ones behind it
    assert peak <= 100 * MB  # clamped to the budget: alone
    assert G.used() == 0


def test_status_reports_queued_tag(small_budget):
    entered, release = threading.Event(), threading.Event()

    def big():
        with G.hold(90 * MB, tag="aaaaaaaaaaaa"):
            entered.set()
            release.wait(10)

    def waiter():
        with G.hold(50 * MB, tag="bbbbbbbbbbbb"):
            pass

    t1 = threading.Thread(target=big)
    t1.start()
    entered.wait(5)
    t2 = threading.Thread(target=waiter)
    t2.start()
    for _ in range(100):
        if G.status(["bbbbbbbbbbbb"])["queued"]:
            break
        time.sleep(0.02)
    st = G.status(["bbbbbbbbbbbb"])
    assert st["queued"] and st["waiting"] == 1 and st["running"] == 1
    assert not G.status(["aaaaaaaaaaaa"])["queued"]
    release.set()
    t1.join(5)
    t2.join(5)
    assert not G.status(["bbbbbbbbbbbb"])["queued"] and G.used() == 0


def test_nested_hold_and_timeout(small_budget):
    with G.hold(90 * MB):
        with G.hold(90 * MB):  # same thread: no second share, no deadlock
            assert G.used() == 90 * MB
        out = []

        def other():
            try:
                with G.hold(50 * MB, timeout=0.2):
                    out.append("ran")
            except TimeoutError:
                out.append("timeout")

        t = threading.Thread(target=other)
        t.start()
        t.join(5)
        assert out == ["timeout"]
    assert G.used() == 0 and not G._waiting


def test_cost_scales_with_pixels():
    assert G.cost(0, "prep") == G.MIN_COST
    assert G.cost(100_000_000, "warm") > G.cost(10_000_000, "warm")
    assert G.cost(10**12, "answer") == G.BUDGET


# ---- through the server: parallel uploads of big synthetic sheets queue on the gate and all succeed
pytest.importorskip("fastapi")
pytest.importorskip("httpx")


def _sheet_png(w, h, seed) -> bytes:
    from PIL import Image, ImageDraw

    im = Image.new("L", (w, h), "white")
    d = ImageDraw.Draw(im)
    for x in range(seed * 7, w, max(1, w // 30)):
        d.line([x, 0, x, h], fill="black", width=4)
    b = io.BytesIO()
    im.save(b, "PNG", compress_level=1)
    return b.getvalue()


def test_parallel_big_uploads_queue_and_succeed(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import app.server as S

    monkeypatch.setattr(S, "UPLOADS", tmp_path / "uploads")
    monkeypatch.setattr(S, "SHEET_CHECK", False)
    monkeypatch.setattr(S, "SHEET_TYPES", False)
    monkeypatch.setattr(S, "_gpu_warm", lambda m: None, raising=False)
    # a budget that admits one 30 MP sheet's preparation at a time (8 B/px)
    monkeypatch.setattr(G, "BUDGET", 300 * MB)
    c = TestClient(S.app)
    seen, peak, stop = [], [0], threading.Event()
    real_prepare = S._prepare

    def slow_prepare(*a):
        peak[0] = max(peak[0], G.used())
        time.sleep(0.3)  # long enough for the others to be seen waiting
        return real_prepare(*a)

    monkeypatch.setattr(S, "_prepare", slow_prepare)

    def watch():
        while not stop.is_set():
            st = c.get("/api/queue", params={"rid": "r1"}).json()
            seen.append(st)
            time.sleep(0.05)

    out = {}

    def up(i):
        r = c.post(f"/api/upload?name=big{i}.png&rid=r{i}", content=_sheet_png(6000, 5000, i))
        out[i] = r

    w = threading.Thread(target=watch)
    w.start()
    ts = [threading.Thread(target=up, args=(i,)) for i in range(3)]
    for t in ts:
        t.start()
        time.sleep(0.05)
    for t in ts:
        t.join(120)
    stop.set()
    w.join(5)
    assert all(out[i].status_code == 200 for i in range(3)), {i: out[i].text[:200] for i in out}
    assert peak[0] <= 300 * MB  # one 30 MP prep (240 MB) at a time
    assert max(s["waiting"] for s in seen) >= 1  # the others queued instead of running side by side
    assert G.used() == 0
