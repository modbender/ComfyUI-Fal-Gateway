"""ComfyUI dispatch simulator for tests.

The plain unit tests in this repo call `node.execute(**kwargs)` directly,
which bypasses the layer of ComfyUI we shipped two bugs through:
**the kwarg filter that drops widget values whose names aren't declared
in `class_def.INPUT_TYPES()`**.

This helper mirrors `execution.get_input_data` from ComfyUI
(comfy_execution/graph.py:get_input_info + execution.py:154-218) so a
test can ask "if the user typed THESE widget values, what would actually
land in `**kwargs`?" — including the silent drops.

Why mirror instead of import: ComfyUI's `execution.py` imports `nodes`,
which transitively imports torch and the entire core node registry —
slow, heavyweight, and pins the test to a specific ComfyUI install path.
The filter rule itself is tiny and stable (it's the public contract of
the INPUT_TYPES protocol), so a 10-line mirror is a fair trade.

If ComfyUI ever changes the filter semantics, the mirror would drift —
but that change would be a public-API break that surfaces in every
custom node, not a silent regression. Acceptable risk.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any


def comfyui_kwarg_filter(node_cls: type, widget_inputs: dict[str, Any]) -> dict[str, Any]:
    """Return only those widget_inputs whose names are declared in
    node_cls.INPUT_TYPES() under required / optional / hidden — matching
    what ComfyUI's executor passes into execute() at queue time.

    Mirrors the relevant slice of execution.py:get_input_data — the
    branch at execution.py:184 that silently skips inputs whose
    get_input_info() returns (None, None, None).
    """
    valid_inputs = node_cls.INPUT_TYPES()
    kept: dict[str, Any] = {}
    for name, value in widget_inputs.items():
        in_required = "required" in valid_inputs and name in valid_inputs["required"]
        in_optional = "optional" in valid_inputs and name in valid_inputs["optional"]
        in_hidden = "hidden" in valid_inputs and name in valid_inputs["hidden"]
        if in_required or in_optional or in_hidden:
            kept[name] = value
    return kept


def dispatch(node_cls: type, **widget_inputs: Any) -> Any:
    """Run a node's execute() through the same kwarg filter ComfyUI's
    queue applies. Handles both sync and async execute() (e.g. T2T/I2T
    are async; JsonExtract is sync).

    Use this in tests instead of calling `node.execute(**values)`
    directly when you want to assert behavior that depends on ComfyUI's
    INPUT_TYPES contract — most importantly, that the user-typed widget
    value for a name not in INPUT_TYPES gets dropped before reaching
    Python kwargs.
    """
    kept = comfyui_kwarg_filter(node_cls, widget_inputs)
    fn = node_cls().execute
    if inspect.iscoroutinefunction(fn):
        return asyncio.run(fn(**kept))
    return fn(**kept)
