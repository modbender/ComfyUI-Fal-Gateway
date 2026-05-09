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

    INPUT_TYPES declares ONLY the static widgets (`key_count`, `default`,
    `key_1`). The JS extension in `web/fal_gateway.js` adds `key_2`..`key_N`
    via `node.addWidget` when the user dials key_count up, and removes
    them via `node.widgets.splice` when the user dials it down — same
    pattern as M4's per-model dynamic widgets in this codebase. This
    avoids the LiteGraph quirk where setting widget.type="hidden" +
    computeSize=[0,-4] doesn't actually disable hit testing — clicks
    were still triggering edits on widgets that looked invisible.

    Python execute() takes `key_count` and reads `key_1`..`key_N` from
    **kwargs (all dynamic widget values arrive that way — same as M4
    base.py). Always returns exactly `MAX_OUTPUTS` strings.

    Bumping `MAX_OUTPUTS` requires bumping the matching JS constant. A
    metadata test pins the contract.
    """

    CATEGORY = "Fal-Gateway"
    FUNCTION = "execute"
    OUTPUT_NODE = False
    MAX_OUTPUTS = 10
    RETURN_TYPES = ("STRING",) * 10
    RETURN_NAMES = tuple(f"value_{i + 1}" for i in range(10))

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        # Only the STATIC widgets here. key_2..key_MAX_OUTPUTS are added
        # dynamically by JS based on key_count. `default` lives in required
        # (not optional) so widget order at save time stays stable:
        #   [key_count, default, key_1, <dynamic key_2..key_N>]
        # On load, ComfyUI reconstructs the 3 static widgets and applies
        # widgets_values[0..2] to them; the JS extension reads the trailing
        # values[3..] back into a sidecar Map so dynamic key values restore.
        return {
            "required": {
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
            },
        }

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
