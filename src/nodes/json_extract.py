"""Companion nodes for the schema-mode T2T/I2T flow.

Fan a JSON STRING out by key. Used downstream of `FalGatewayT2T` /
`FalGatewayI2T` when the user filled the `schema` widget — the LLM returns
a JSON object keyed by the schema's fields.

Two variants:

- `FalGatewayJsonExtract` ("JSON Extract (Single)") — one key in, one
  STRING out. Drop one per field you want to extract.

- `FalGatewayJsonExtractMany` ("JSON Extract (Multiple)") — comma-separated
  key list in, N STRING outputs out. The frontend extension watches the
  `keys` widget and shows exactly N output sockets named after each key.
  Cap is `MAX_OUTPUTS = 10`; Python always returns 10 values padded with
  `default`, the JS layer just hides the rest.

Both are generic — no fal dependency. Work with any upstream JSON STRING.
"""

from __future__ import annotations

import json
from typing import Any


def _coerce_value(value: Any, default: str) -> str:
    """Single shared coercion rule: None/missing → default; str passthrough;
    nested objects/arrays serialized; primitives stringified."""
    if value is None:
        return default
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _parse_dict(json_string: str) -> dict[str, Any] | None:
    """Parse a JSON string and return the dict, or None on any failure
    (parse error or non-dict root). Lets callers fall through to defaults."""
    try:
        parsed = json.loads(json_string)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


class FalGatewayJsonExtract:
    CATEGORY = "Fal-Gateway"
    FUNCTION = "execute"
    OUTPUT_NODE = False
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("value",)

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {
            "required": {
                "json_string": ("STRING", {"default": "", "multiline": True, "forceInput": True}),
                "key": ("STRING", {"default": ""}),
            },
            "optional": {
                "default": ("STRING", {"default": ""}),
            },
        }

    def execute(
        self,
        json_string: str,
        key: str,
        default: str = "",
    ) -> tuple[str]:
        parsed = _parse_dict(json_string)
        if parsed is None or key not in parsed:
            return (default,)
        return (_coerce_value(parsed[key], default),)


class FalGatewayJsonExtractMany:
    """Multi-key JSON extractor with R2V-style +/- counter UX.

    UI shape (mirrors `FalGatewayRef2V`'s `image_count` → image_N socket
    pattern):
      - `key_count`: INT widget, +/- arrows, range 1..MAX_OUTPUTS
      - `default`: STRING widget — value used when a key is missing
      - `key_1`..`key_N`: single-line STRING widgets, one per active row
      - N output sockets named after each key's current value

    INPUT_TYPES declares ALL `key_N` widgets (key_1 in required, key_2..N
    in optional). This is non-negotiable: ComfyUI's get_input_info()
    drops widget values whose names aren't in INPUT_TYPES (see
    comfy_execution/graph.py:84-94 + execution.py:184). If we only
    declared key_1 and added key_2..N dynamically by JS, ComfyUI's
    queue would silently drop the user's typed values for key_2..N
    and Python's **kwargs would only ever see key_1 — every output
    past the first comes back empty. (M4's per-model widgets paper
    over the same drop with kwargs.get(name, w.default) fallback to
    the OpenAPI schema default; we don't have that fallback here.)

    The JS extension in `web/fal_gateway.js` still splices the excess
    key_N widgets OUT of node.widgets when key_count drops, which
    keeps them off-canvas and out of LiteGraph's hit-test path. The
    INPUT_TYPES declaration is purely for ComfyUI's input-routing —
    the widgets exist briefly at node init, JS rearranges them, and
    only the visible ones are sent to Python at queue time.

    Always returns exactly `MAX_OUTPUTS` strings — slots beyond the
    active key_count get the `default` value. Bumping `MAX_OUTPUTS`
    requires bumping the matching JS constant. A metadata test pins
    both the count contract AND the "all key_N must be declared"
    invariant as canaries.
    """

    CATEGORY = "Fal-Gateway"
    FUNCTION = "execute"
    OUTPUT_NODE = False
    MAX_OUTPUTS = 10
    RETURN_TYPES = ("STRING",) * 10
    RETURN_NAMES = tuple(f"value_{i + 1}" for i in range(10))

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        # ALL key_N widgets MUST be declared here, even though the JS
        # extension dynamically shows/hides them based on key_count. See
        # the class docstring for the ComfyUI input-dropping invariant.
        # Static widget order at save time:
        #   required: [key_count, default, key_1]   (json_string is forceInput → socket)
        #   optional: [key_2, key_3, ..., key_10]
        # widgets_values is positional, so on load values[0..2] map to
        # the 3 required widgets, values[3..] to the visible key_N up to
        # whatever count was saved. JS in onConfigure splices the rest.
        required: dict[str, Any] = {
            "json_string": (
                "STRING",
                {"default": "", "multiline": True, "forceInput": True},
            ),
            "key_count": (
                "INT",
                {"default": 1, "min": 1, "max": cls.MAX_OUTPUTS, "step": 1},
            ),
            "default": ("STRING", {"default": ""}),
            "key_1": ("STRING", {"default": ""}),
        }
        optional: dict[str, Any] = {}
        for i in range(2, cls.MAX_OUTPUTS + 1):
            optional[f"key_{i}"] = ("STRING", {"default": ""})
        return {"required": required, "optional": optional}

    def execute(
        self,
        json_string: str,
        key_count: int,
        default: str = "",
        **keys: str,
    ) -> tuple[str, ...]:
        # Clamp to declared range — defends against JS hand-edits or stale
        # workflows that saved an out-of-range value.
        n = max(1, min(int(key_count or 1), self.MAX_OUTPUTS))
        parsed = _parse_dict(json_string) or {}

        values: list[str] = []
        for i in range(1, n + 1):
            key = (keys.get(f"key_{i}") or "").strip()
            if not key:
                values.append(default)
                continue
            values.append(_coerce_value(parsed.get(key), default))

        # Pad to MAX_OUTPUTS so the tuple length always matches RETURN_TYPES.
        # The JS extension trims visible output sockets to the active count.
        values.extend([""] * (self.MAX_OUTPUTS - len(values)))
        return tuple(values)
