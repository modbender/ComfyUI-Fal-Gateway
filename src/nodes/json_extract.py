"""Companion node for the schema-mode T2T/I2T flow.

Fans a JSON STRING out by key. Used downstream of `FalGatewayT2T` /
`FalGatewayI2T` when the user filled the `schema` widget — the LLM returns
a JSON object keyed by the schema's fields, and one `JSONExtract` per
field pulls out a STRING value for the next node in the graph.

Generic by design: doesn't depend on fal at all. Works with any upstream
JSON STRING.
"""

from __future__ import annotations

import json
from typing import Any


class FalGatewayJsonExtract:
    CATEGORY = "Fal-Gateway"
    FUNCTION = "execute"
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
        try:
            parsed = json.loads(json_string)
        except (TypeError, ValueError):
            return (default,)

        if not isinstance(parsed, dict):
            return (default,)

        if key not in parsed:
            return (default,)

        value = parsed[key]
        if value is None:
            return (default,)

        # Strings pass through; everything else (int/float/bool/list/dict) is
        # coerced so downstream STRING-typed sockets get a usable value. Nested
        # objects/arrays are serialized so the graph stays composable.
        if isinstance(value, str):
            return (value,)
        if isinstance(value, (dict, list)):
            return (json.dumps(value, ensure_ascii=False),)
        return (str(value),)
