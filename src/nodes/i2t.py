from __future__ import annotations

from typing import Any

from .base import _FalGatewayNodeBase


class FalGatewayI2T(_FalGatewayNodeBase):
    CATEGORY_FILTER = "vision"
    SHAPE_FILTER = ()  # VLMs may or may not have IMAGE_INPUT in schema; accept all
    NODE_DISPLAY_LABEL = "Fal Image-to-Text"
    OUTPUT_KIND = "text"
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("response", "info")

    @classmethod
    def image_socket_names(cls) -> tuple[str, ...]:
        return ("image",)

    @classmethod
    def extra_required_widgets(cls) -> dict[str, Any]:
        # `system_prompt` is natively supported by `openrouter/router/vision`
        # (Claude/Gemini/GPT-4o, etc.); fal-direct vision endpoints
        # (Florence-2, Moondream) ignore unknown fields, so wiring it as a
        # universal widget is safe. Mirrors T2T for parity — the same
        # "instruct the model" capability across both nodes.
        # `schema` (empty by default) toggles JSON output mode — see
        # `src/json_mode.py`. Only honored when dispatching through
        # `openrouter/router/vision`; fal-direct vision endpoints silently
        # drop it. Pair with FalGatewayJsonExtract downstream to fan the
        # JSON out by key.
        return {
            "system_prompt": ("STRING", {"default": "", "multiline": True}),
            "schema": ("STRING", {"default": "", "multiline": True}),
        }
