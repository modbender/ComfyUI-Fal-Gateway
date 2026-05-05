"""Tests for the package entry point — `__init__.py`.

The package's `__init__.py` runs ONLY inside ComfyUI's runtime (its
imports are gated on `from server import PromptServer`). Pytest never
exercises that code path, so a rename like `src/server_routes.py` →
`src/routes.py` that forgets to update `__init__.py` will silently break
node registration in production while every test passes locally.

Defense: AST-parse `__init__.py` and verify every relative `from .src.X`
import resolves to a real module under `src/`. Catches stale imports
before they reach a user's ComfyUI.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path


_INIT_PATH = Path(__file__).resolve().parent.parent / "__init__.py"


def _parse_relative_imports() -> list[str]:
    """Return every `from .src.X[.Y]` module name referenced in __init__.py."""
    tree = ast.parse(_INIT_PATH.read_text(encoding="utf-8"))
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module is None:
            continue
        if node.level == 0:  # absolute import — not our concern
            continue
        if not node.module.startswith("src"):
            continue
        out.append(node.module)
    return out


def test_init_only_references_existing_src_modules():
    """Every `from .src.X import …` in __init__.py must resolve to a real
    module under src/. Catches rename-without-updating-__init__ bugs."""
    failures: list[str] = []
    for module_name in _parse_relative_imports():
        try:
            importlib.import_module(module_name)
        except ImportError as exc:
            failures.append(f"  - {module_name}: {exc}")

    assert not failures, (
        "Stale imports in __init__.py — ComfyUI registration will silently fail "
        "because the gated try/except swallows these errors:\n" + "\n".join(failures)
    )


def test_init_imports_node_class_mappings():
    """Sanity: __init__.py must source NODE_CLASS_MAPPINGS from src.nodes
    so ComfyUI's node menu actually shows our nodes."""
    relative_modules = _parse_relative_imports()
    assert "src.nodes" in relative_modules, (
        "__init__.py must `from .src.nodes import NODE_CLASS_MAPPINGS` — "
        "without this ComfyUI registers zero nodes from this package."
    )


def test_init_imports_register_routes():
    """Sanity: __init__.py must wire HTTP routes via register_routes()."""
    src = _INIT_PATH.read_text(encoding="utf-8")
    assert "register_routes" in src, (
        "__init__.py must call register_routes() to wire /fal_gateway/* HTTP routes. "
        "Without this the schema endpoint, refresh menu, and pricing fetch break."
    )
