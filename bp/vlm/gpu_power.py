"""On-demand power for the live-VLM GPU box: start it when an upload needs it, stop it when idle, cap the daily cost.

    from bp.vlm.gpu_power import get_power
    pw = get_power()
    pw.ensure_started()   # non-blocking; "ready" | "starting" | "refused" | "off"
    pw.state()            # "off" | "starting" | "ready"  (health of <BP_VLM_URL>/models, cached 5 s)
    pw.touch()            # on every live VLM use (bp/vlm/live.py); resets the idle clock
    pw.status()           # {"state", "eta_s", "spent_today", "cap_usd", "hooked", ...}  (GET /api/gpu)

The demo VM holds no cloud-provider key: starting and stopping go through a hook that the infra side runs
(contract: deploy/vlm/POWER.md). We POST {"action": "start"} / {"action": "stop"} to $BP_GPU_HOOK_URL with
"Authorization: Bearer $BP_GPU_HOOK_SECRET". A background watcher stops the box after $BP_GPU_IDLE_MIN minutes
without a live ask, and when today's (UTC) local cost estimate reaches $BP_GPU_DAILY_USD_CAP; a start is refused
once the cap is reached. Every start / stop / refusal is a line in cache/gpu_power.jsonl (the ledger the cost
estimate is computed from, so it survives restarts).

Environment
- BP_GPU_HOOK_URL       unset -> no hook: a no-op that reports state from health only (the box is always on)
- BP_GPU_HOOK_SECRET    shared secret, sent as a bearer token (never logged)
- BP_GPU_IDLE_MIN       12      idle minutes before a stop
- BP_GPU_DAILY_USD_CAP  15      local daily budget (UTC day), USD
- BP_GPU_USD_PER_H      2.89    the box's hourly price, USD
- BP_GPU_BOOT_S         150     expected boot-to-ready time (the hook's eta_s overrides it per start)
- BP_GPU_BOOT_MAX_S     900     a start that is not healthy after this long counts as failed (state "off")
- BP_GPU_LEDGER         cache/gpu_power.jsonl

Never raises into callers; never prints the secret or the VLM key.
"""
from __future__ import annotations

import datetime
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

OFF, STARTING, READY = "off", "starting", "ready"
HEALTH_TTL_S = 5.0
HOOK_TIMEOUT_S = 10.0
COOLDOWN_S = 60.0  # at most one start (and one stop) request per minute: the contract's rate limit


def _env_f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


def _day_start(ts: float) -> float:
    d = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).date()
    return datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc).timestamp()


class GpuPower:
    def __init__(self, hook_url: str | None = None, secret: str | None = None, *, idle_min: float | None = None,
                 cap_usd: float | None = None, usd_per_h: float | None = None, boot_s: float | None = None,
                 boot_max_s: float | None = None, ledger: str | Path | None = None, health=None,
                 clock=time.time, watch: bool = True, check_s: float = 30.0):
        env = os.environ
        self.hook_url = hook_url if hook_url is not None else (env.get("BP_GPU_HOOK_URL") or None)
        self._secret = secret if secret is not None else env.get("BP_GPU_HOOK_SECRET", "")
        self.idle_s = 60.0 * (idle_min if idle_min is not None else _env_f("BP_GPU_IDLE_MIN", 12))
        self.cap_usd = cap_usd if cap_usd is not None else _env_f("BP_GPU_DAILY_USD_CAP", 15)
        self.usd_per_h = usd_per_h if usd_per_h is not None else _env_f("BP_GPU_USD_PER_H", 2.89)
        self.boot_s = boot_s if boot_s is not None else _env_f("BP_GPU_BOOT_S", 150)
        self.boot_max_s = boot_max_s if boot_max_s is not None else _env_f("BP_GPU_BOOT_MAX_S", 900)
        self.ledger = Path(ledger or env.get("BP_GPU_LEDGER") or "cache/gpu_power.jsonl")
        self._health = health or _vlm_health
        self.clock = clock
        self.check_s = check_s
        self._lock = threading.RLock()
        self._health_at, self._health_ok = -1e18, False
        self._intervals: list[list] = []  # [on_ts, off_ts | None]: billed time, from the ledger
        self._start_ts: float | None = None   # when the current start was accepted by the hook
        self._eta_s = self.boot_s
        self._starting = False                # a start request is in flight
        self._last_start_try = self._last_stop_try = -1e18
        self._last_refused_log = -1e18
        self.last_use = clock()
        self.last_error: str | None = None
        self._load_ledger()
        if self._open() is not None:  # restarted while the box was billed: idle clock and boot window start now
            self._start_ts = clock()
        self._watcher = None
        if self.hooked and watch:
            self._watcher = threading.Thread(target=self._watch, name="gpu-power-idle", daemon=True)
            self._watcher.start()

    # ------------------------------------------------------------------ public
    @property
    def hooked(self) -> bool:
        return bool(self.hook_url)

    def touch(self):
        self.last_use = self.clock()

    def state(self) -> str:
        """off | starting | ready. Without a hook: health only (ready or off). With one, the box is only probed
        while we believe it is on (an accepted start, or one in flight), so a stopped box costs no probe."""
        if not self.hooked:
            return READY if self._healthy() else OFF
        with self._lock:
            on, starting, st = self._open() is not None, self._starting, self._start_ts
        if not on and not starting:
            return OFF
        if on and self._healthy():
            return READY
        now = self.clock()
        if starting or (st is not None and now - st < self.boot_max_s):
            return STARTING
        return OFF  # accepted but never became healthy: failed boot (the idle watcher will send a stop)

    def ensure_started(self) -> str:
        """Ask the hook to start the box, in a background thread; returns at once.
        "ready" | "starting" | "refused" (daily cap) | "off" (no hook / VLM not configured / hook failing)."""
        if not self.hooked:
            return self.state()
        now = self.clock()
        with self._lock:
            self.last_use = now
            if self._starting:
                return STARTING
            o = self._open()
            if o is not None:
                if self._health_ok and now - self._health_at < HEALTH_TTL_S:
                    return READY
                if now - (self._start_ts or o[0]) < self.boot_max_s:
                    return STARTING
                # billed but never became healthy: ask again (idempotent on the hook side), within the cooldown
            spent = self.spent_today(now)
            if spent >= self.cap_usd:
                if now - self._last_refused_log > 600:
                    self._last_refused_log = now
                    self._log({"event": "start_refused", "reason": "daily cap", "spent_today": round(spent, 2),
                               "cap_usd": self.cap_usd})
                return "refused"
            if now - self._last_start_try < COOLDOWN_S:
                return OFF  # the last start failed less than a minute ago
            self._last_start_try = now
            self._starting = True
        threading.Thread(target=self._do_start, name="gpu-power-start", daemon=True).start()
        return STARTING

    def eta_s(self) -> float:
        """Seconds until the box should be ready (0 when ready; the full boot time when off)."""
        s = self.state()
        if s == READY:
            return 0.0
        if s == STARTING and self._start_ts is not None:
            return max(5.0, self._eta_s - (self.clock() - self._start_ts))
        return float(self._eta_s)

    def spent_today(self, now: float | None = None) -> float:
        """Local cost estimate for today (UTC): billed on-time since midnight x the hourly price."""
        now = self.clock() if now is None else now
        d0 = _day_start(now)
        with self._lock:
            secs = sum(max(0.0, min(off if off is not None else now, now) - max(on, d0))
                       for on, off in self._intervals)
        return secs / 3600.0 * self.usd_per_h

    def status(self) -> dict:
        s = self.state()
        return {"state": s, "eta_s": round(self.eta_s()), "boot_s": round(self._eta_s),
                "spent_today": round(self.spent_today(), 2), "cap_usd": self.cap_usd, "hooked": self.hooked,
                "idle_min": round(self.idle_s / 60, 1)}

    def tick(self):
        """One watcher step (also called by tests): stop after the idle time, or when the daily cap is reached."""
        if not self.hooked:
            return None
        now = self.clock()
        with self._lock:
            on = self._open() is not None
            if not on or self._starting or now - self._last_stop_try < COOLDOWN_S:
                return None
            if self.spent_today(now) >= self.cap_usd:
                reason = "daily cap"
            elif now - self.last_use >= self.idle_s:
                reason = f"idle {self.idle_s / 60:g} min"
            else:
                return None
            self._last_stop_try = now
        return self._do_stop(reason)

    # ------------------------------------------------------------------ internals
    def _open(self):
        return self._intervals[-1] if self._intervals and self._intervals[-1][1] is None else None

    def _healthy(self) -> bool:
        now = self.clock()
        if now - self._health_at < HEALTH_TTL_S:
            return self._health_ok
        try:
            ok = bool(self._health())
        except Exception:  # noqa: BLE001
            ok = False
        self._health_at, self._health_ok = self.clock(), ok
        return ok

    def _post(self, action: str) -> dict:
        body = json.dumps({"action": action}).encode()
        req = urllib.request.Request(self.hook_url, data=body, method="POST", headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {self._secret}",
            "User-Agent": "bp-gpu-power/1"})
        with urllib.request.urlopen(req, timeout=HOOK_TIMEOUT_S) as r:
            raw = r.read()
        try:
            out = json.loads(raw or b"{}")
        except ValueError:
            out = {}
        return out if isinstance(out, dict) else {}

    def _do_start(self):
        try:
            out = self._post("start")
        except Exception as e:  # noqa: BLE001
            self.last_error = _err(e)
            self._log({"event": "start_failed", "error": self.last_error})
            with self._lock:
                self._starting = False
            return
        now = self.clock()
        with self._lock:
            eta = out.get("eta_s")
            self._eta_s = float(eta) if isinstance(eta, (int, float)) and 0 < eta < 3600 else self.boot_s
            if self._open() is None:
                self._intervals.append([now, None])
            self._start_ts = now
            self.last_use = now
            self._health_at = -1e18  # probe again now
            self._starting = False
        self._log({"event": "start", "hook_state": str(out.get("state", ""))[:20], "eta_s": self._eta_s})

    def _do_stop(self, reason: str):
        try:
            out = self._post("stop")
        except Exception as e:  # noqa: BLE001  stays billed; retried after the cooldown
            self.last_error = _err(e)
            self._log({"event": "stop_failed", "reason": reason, "error": self.last_error})
            return False
        now = self.clock()
        with self._lock:
            o = self._open()
            if o is not None:
                o[1] = now
            self._start_ts = None
            self._health_at, self._health_ok = -1e18, False
        self._log({"event": "stop", "reason": reason, "hook_state": str(out.get("state", ""))[:20],
                   "spent_today": round(self.spent_today(now), 2)})
        return True

    def _watch(self):
        while True:
            time.sleep(self.check_s)
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001  the watcher never dies
                self.last_error = _err(e)

    def _log(self, row: dict):
        now = self.clock()
        row = {"ts": round(now, 3),
               "utc": datetime.datetime.fromtimestamp(now, datetime.timezone.utc).isoformat(timespec="seconds"),
               **row}
        try:
            self.ledger.parent.mkdir(parents=True, exist_ok=True)
            with open(self.ledger, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
        except OSError:
            pass

    def _load_ledger(self):
        """Rebuild the billed intervals from the ledger (only the last two days matter for the daily cap)."""
        try:
            lines = self.ledger.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        horizon = _day_start(self.clock()) - 86400
        for line in lines:
            try:
                r = json.loads(line)
                ts, ev = float(r["ts"]), r["event"]
            except (ValueError, KeyError, TypeError):
                continue
            if ev == "start" and self._open() is None:
                self._intervals.append([ts, None])
            elif ev == "stop" and self._open() is not None:
                self._open()[1] = ts
        self._intervals = [iv for iv in self._intervals if iv[1] is None or iv[1] >= horizon]


def _err(e: Exception) -> str:
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    return f"{type(e).__name__}: {str(e)[:120]}"


def _vlm_health() -> bool:
    from bp.vlm.live import health

    return health(timeout=3.0) == "ok"


_power: GpuPower | None = None
_power_lock = threading.Lock()


def get_power() -> GpuPower:
    """The process-wide instance (built from the environment on first use)."""
    global _power
    with _power_lock:
        if _power is None:
            _power = GpuPower()
        return _power


def live_allowed() -> bool:
    """bp/vlm/live.py asks this before a live call: always True without a hook (today's behaviour);
    with one, only when the box is ready (a stopped box is never waited on). Counts as a use when True."""
    pw = get_power()
    if pw.hooked and pw.state() != READY:
        return False
    pw.touch()
    return True
