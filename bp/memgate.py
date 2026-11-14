"""A process-wide memory budget for heavy image work (upload preparation, sheet warm-ups, specialist answers on big
sheets, /api/walls).

Each job estimates what it will hold at its peak from the sheet's pixel count (`cost`) and takes that much from one
budget (BP_MEM_BUDGET_GB, default 8) before it starts; when the budget is full it waits in line instead of starting,
so a burst of large uploads queues rather than pushing the server past its container limit (12 GB on the demo VM).
A job costing more than the whole budget runs alone. Nested holds on the same thread take nothing more (a warm-up
that reads the sheet inside a gated answer does not deadlock on itself).

`status(tags)` says whether jobs for given uploads are waiting; the UI polls it (GET /api/queue) to show
"Queued behind other uploads…".
"""
from __future__ import annotations

import contextlib
import ctypes
import gc
import os
import threading
import time

GB = 1 << 30
BUDGET = int(float(os.environ.get("BP_MEM_BUDGET_GB", "8")) * GB)
# bytes held at peak per pixel of the sheet, by stage. Measured on the four hi-res examples (67-139 MP) pinned to
# 4 cores: peak RSS over the idle server divided by pixels, rounded up (see tests/test_memgate.py for the gate itself)
BPP = {"prep": 8, "warm": 24, "answer": 24, "walls": 12}
MIN_COST = 64 << 20  # the smallest job still holds a few copies of a small image and the libraries' scratch

_cond = threading.Condition()
_used = 0
_waiting: list[dict] = []   # jobs in line, oldest first: {"tag", "cost", "label", "t"}
_running: list[dict] = []
_local = threading.local()

DEBUG = os.environ.get("BP_MEMGATE_LOG") == "1"  # log each job's cost against the RSS seen while it ran


def _rss() -> int:
    try:
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError):
        return 0


def _sampler():
    while True:
        r = _rss()
        with _cond:
            for j in _running:
                j["peak"] = max(j.get("peak", 0), r)
        time.sleep(0.1)


if DEBUG:
    threading.Thread(target=_sampler, daemon=True, name="memgate-rss").start()

try:
    _libc = ctypes.CDLL("libc.so.6")
except OSError:  # not glibc
    _libc = None


def cost(pixels: int | float, stage: str) -> int:
    """Bytes a `stage` job on a `pixels`-pixel sheet holds at its peak (never more than the whole budget)."""
    return int(min(BUDGET, max(MIN_COST, float(pixels or 0) * BPP.get(stage, 24))))


def _trim():
    """Hand freed heap back to the OS (glibc keeps it otherwise, and RSS would stay at the last peak)."""
    gc.collect()
    if _libc is not None:
        try:
            _libc.malloc_trim(0)
        except Exception:  # noqa: BLE001
            pass


@contextlib.contextmanager
def hold(nbytes: int, tag: str = "", label: str = "", timeout: float | None = None):
    """Take `nbytes` of the budget for the duration of the block, waiting in line (FIFO) while it is full.
    Raises TimeoutError after `timeout` seconds in line (None: wait as long as it takes)."""
    global _used
    if getattr(_local, "depth", 0):  # this thread already holds its share
        _local.depth += 1
        try:
            yield
        finally:
            _local.depth -= 1
        return
    nbytes = int(min(BUDGET, max(1, nbytes)))
    me = {"tag": tag, "cost": nbytes, "label": label, "t": time.time()}
    end = None if timeout is None else time.monotonic() + timeout
    with _cond:
        _waiting.append(me)
        try:
            # first in line, and it fits (or nothing else runs: a job bigger than the budget runs alone)
            while not (_waiting[0] is me and (_used + nbytes <= BUDGET or _used == 0)):
                left = None if end is None else end - time.monotonic()
                if left is not None and left <= 0:
                    raise TimeoutError(f"memory budget busy for {timeout:.0f} s")
                _cond.wait(left if left is not None else 5.0)
        finally:
            _waiting.remove(me)
            _cond.notify_all()  # the next in line may fit now
        _used += nbytes
        me["rss0"], me["t0"] = (_rss() if DEBUG else 0), time.time()
        _running.append(me)
    _local.depth = 1
    try:
        yield
    finally:
        _local.depth = 0
        _trim()
        with _cond:
            _used -= nbytes
            _running.remove(me)
            _cond.notify_all()
            if DEBUG:
                print(f"memgate {label or tag}: cost {nbytes >> 20} MB, waited {me['t0'] - me['t']:.1f} s, ran "
                      f"{time.time() - me['t0']:.1f} s, rss {me['rss0'] >> 20} -> peak {me.get('peak', 0) >> 20} MB "
                      f"(+{(me.get('peak', 0) - me['rss0']) >> 20}), {len(_running)} running, {_used >> 20} MB held",
                      flush=True)


def status(tags=()) -> dict:
    """{"queued": a job of one of `tags` is waiting, "ahead": jobs in line before the first of them, "waiting": jobs
    in line, "running": jobs holding budget, "used_gb", "budget_gb"}."""
    tags = {t for t in tags if t}
    with _cond:
        pos = next((i for i, w in enumerate(_waiting) if w["tag"] in tags), None)
        return {"queued": pos is not None, "ahead": pos if pos is not None else 0, "waiting": len(_waiting),
                "running": len(_running), "used_gb": round(_used / GB, 2), "budget_gb": round(BUDGET / GB, 2)}


def tag_for(path) -> str:
    """The upload a file belongs to (its cache/uploads/<key> folder name), the tag the UI asks about; else ''."""
    import re

    d = os.path.basename(os.path.dirname(str(path or "")))
    return d if re.fullmatch(r"[0-9a-f]{12}", d) else ""


def used() -> int:
    with _cond:
        return _used
