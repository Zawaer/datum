"""Solver registry. A solver is a callable q -> dict with keys:
answer (None = abstain), confidence (0..1), evidence (list), cost_usd, method.
"""
import importlib

SOLVERS = {
    "prior": "bp.solvers.prior:PriorSolver",
    "claude": "bp.solvers.claude_vlm:ClaudeSolver",
}


def get_solver(name: str, **kw):
    base, _, variant = name.partition("@")
    mod, cls = SOLVERS[base].split(":")
    c = getattr(importlib.import_module(mod), cls)
    return c(variant=variant or None, **kw)
