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
    """Multi-key JSON extractor — single multiline `keys` textarea, N outputs.

    Why this shape (and NOT the R2V-style `key_count + key_N` widgets):
    LiteGraph's `computeSize` hard-codes `rows = max(inputs, outputs)` and
    stacks widgets *below* the slot strip — there's no path to "outputs
    aligned with widget rows" without writing custom row widgets the way
    rgthree's Power LoRA Loader does (~500 lines of canvas code, fragile
    across LG versions). Per-row widgets that hide/show based on a counter
    create a permanent visual mismatch (right column has N output dots,
    left column has only the visible widgets — empty band on the left).

    Single-textarea form sidesteps the whole layout fight: one short widget
    holds all keys, N output sockets sit on the right and rename live as
    the user types. Widget area stays compact, output strip drives node
    height naturally, no dead space.

    Python always returns exactly `MAX_OUTPUTS` strings — slots beyond the
    parsed key count get the `default` value. JS extension watches the
    `keys` widget, parses the comma-separated list, syncs output socket
    count + names. Cap at 10 keys.
    """

    CATEGORY = "Fal-Gateway"
    FUNCTION = "execute"
    OUTPUT_NODE = False
    MAX_OUTPUTS = 10
    RETURN_TYPES = ("STRING",) * 10
    RETURN_NAMES = tuple(f"value_{i + 1}" for i in range(10))

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {
            "required": {
                "json_string": (
                    "STRING",
                    {"default": "", "multiline": True, "forceInput": True},
                ),
                "keys": (
                    "STRING",
                    {"default": "", "multiline": True},
                ),
            },
            "optional": {
                "default": ("STRING", {"default": ""}),
            },
        }

    def execute(
        self,
        json_string: str,
        keys: str,
        default: str = "",
    ) -> tuple[str, ...]:
        keys_list = [k.strip() for k in keys.split(",") if k.strip()]
        parsed = _parse_dict(json_string) or {}

        values = [
            _coerce_value(parsed.get(k), default)
            for k in keys_list[: self.MAX_OUTPUTS]
        ]
        # Pad to MAX_OUTPUTS so tuple length always matches RETURN_TYPES.
        # The JS extension trims the visible sockets to len(keys_list).
        values.extend([""] * (self.MAX_OUTPUTS - len(values)))
        return tuple(values)
