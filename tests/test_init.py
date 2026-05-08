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


# ---- Registry-indexer compatibility -------------------------------------
#
# The Comfy Registry indexer (registry.comfy.org) imports the package
# without ComfyUI present and reads NODE_CLASS_MAPPINGS to build its
# search index. If the import is gated behind ComfyUI's `server` module,
# the registry sees zero nodes — the package shows up but has no
# "Nodes matched: …" line on its detail page (verified empirically:
# 0.3.1 published with the gated import → registry showed no node list).


import sys  # noqa: E402
import importlib.util  # noqa: E402


def _import_package_without_server() -> object:
    """Load __init__.py with ComfyUI's `server` module blocked, mimicking
    what the registry indexer does in its sandboxed import."""

    class _BlockServer:
        def find_module(self, name, path=None):
            if name == "server" or name.startswith("server."):
                raise ImportError("server blocked for test")

    blocker = _BlockServer()
    sys.meta_path.insert(0, blocker)
    mod_name = "fal_gateway_under_test"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(
        mod_name,
        _INIT_PATH,
        submodule_search_locations=[str(_INIT_PATH.parent)],
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.meta_path.remove(blocker)
    return mod


def test_node_class_mappings_populated_without_comfyui_server():
    """Without ComfyUI's `server` module the package still exposes its
    full node list. Critical for registry indexer + linters/packagers."""
    mod = _import_package_without_server()
    assert len(mod.NODE_CLASS_MAPPINGS) >= 10, (
        f"registry must see at least 10 nodes; got {list(mod.NODE_CLASS_MAPPINGS.keys())}"
    )
    for expected in ("FalGatewayT2V", "FalGatewayT2T", "FalGatewayI2T", "FalGatewayJsonExtract"):
        assert expected in mod.NODE_CLASS_MAPPINGS, f"{expected} missing"


def test_display_names_match_class_keys_without_server():
    mod = _import_package_without_server()
    assert set(mod.NODE_CLASS_MAPPINGS.keys()) == set(mod.NODE_DISPLAY_NAME_MAPPINGS.keys())
