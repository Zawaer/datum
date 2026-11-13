"""Fill the on-disk caches (IFC tables, Swiss parses, 3D meshes, YOLO load) so first asks are fast.

Runs inside the app container with paid calls disabled:  docker compose exec -e CLAUDE_CLI=/bin/false app python warm.py
Prints per-source accuracy on the bundle's questions it asked (first 3 per drawing) as a smoke test.
"""
import collections
import sys
import time

sys.path.insert(0, "/app")
from app.mesh import mesh_bytes  # noqa: E402
from app.server import BY_PATH, ifc_for, router  # noqa: E402
from bp.score import is_correct  # noqa: E402

ok, n, t = collections.Counter(), collections.Counter(), collections.Counter()
for path, qs in sorted(BY_PATH.items()):
    src = qs[0]["source"]
    for q in qs[:3]:
        t0 = time.time()
        r = router(q)
        t[src] += time.time() - t0
        n[src] += 1
        try:
            ok[src] += bool(r.get("answer") is not None and is_correct(q["type"], r["answer"], q["answer"]))
        except Exception:  # noqa: BLE001
            pass
    if (m := ifc_for(path)) is not None:
        try:
            mesh_bytes(m)
        except Exception as e:  # noqa: BLE001
            print("mesh failed", path, e)
    print(f"{src:16s} {path[:70]:70s} {time.time() - t0:6.1f}s", flush=True)
for s in n:
    print(f"{s:16s} {ok[s]}/{n[s]} correct, {t[s] / n[s]:.2f} s/q")
