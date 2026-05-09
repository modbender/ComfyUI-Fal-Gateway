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
      - `key_1`..`key_N`: single-line STRING widgets, one per active row
      - N output sockets named after each key's current value

    All `key_1`..`key_MAX_OUTPUTS` widgets are declared in INPUT_TYPES so
    ComfyUI can serialize/restore their values across save+load. The JS
    extension in `web/fal_gateway.js` hides the excess (key_(N+1)..) when
    the user dials key_count down, and renames output sockets to mirror
    each key widget's value.

    Python always returns exactly `MAX_OUTPUTS` strings — values for
    inactive keys are empty strings — so RETURN_TYPES stays static.

    Bumping `MAX_OUTPUTS` requires bumping the matching JS constant. A
    metadata test pins the contract; if you bump here without bumping
    there the test fails as a canary.
    """

    CATEGORY = "Fal-Gateway"
    FUNCTION = "execute"
    OUTPUT_NODE = False
    MAX_OUTPUTS = 10
    RETURN_TYPES = ("STRING",) * 10
    RETURN_NAMES = tuple(f"value_{i + 1}" for i in range(10))

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        required: dict[str, Any] = {
            "json_string": (
                "STRING",
                {"default": "", "multiline": True, "forceInput": True},
            ),
            "key_count": (
                "INT",
                {"default": 1, "min": 1, "max": cls.MAX_OUTPUTS, "step": 1},
            ),
        }
        for i in range(1, cls.MAX_OUTPUTS + 1):
            required[f"key_{i}"] = (
                "STRING",
                {"default": "", "multiline": False},
            )
        return {
            "required": required,
            "optional": {
                "default": ("STRING", {"default": ""}),
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
        # The trailing sockets are hidden in the UI when key_count < MAX.
        values.extend([""] * (self.MAX_OUTPUTS - len(values)))
        return tuple(values)
