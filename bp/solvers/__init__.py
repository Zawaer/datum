"""Solver registry. Contract and evidence format: docs/EVIDENCE.md."""
import importlib

SOLVERS = {
    "router": "bp.router:Router",
    "prior": "bp.solvers.prior:PriorSolver",
    "claude": "bp.solvers.claude_vlm:ClaudeSolver",
    "gemini": "bp.solvers.gemini_vlm:GeminiSolver",
    "swiss": "bp.solvers.swiss:SwissSolver",
    "ifc": "bp.solvers.ifc:IfcSolver",
    "cubicasa": "bp.solvers.cubicasa:CubicasaSolver",
    "generic": "bp.solvers.generic:GenericSolver",
    "vlm": "bp.solvers.vlm:VlmSolver",
    "ifctext": "bp.solvers.ifctext:IfcTextSolver",
}


def get_solver(name: str, **kw):
    base, _, variant = name.partition("@")
    mod, cls = SOLVERS[base].split(":")
    c = getattr(importlib.import_module(mod), cls)
    return c(variant=variant or None, **kw)
