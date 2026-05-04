from __future__ import annotations

from typing import Any

from .base import _FalGatewayNodeBase


class FalGatewayT2T(_FalGatewayNodeBase):
    CATEGORY_FILTER = "llm"
    SHAPE_FILTER = ()  # All LLMs are text-only; no shape filtering needed
    NODE_DISPLAY_LABEL = "Fal Text-to-Text"
    OUTPUT_KIND = "text"
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("response", "info")

    @classmethod
    def extra_required_widgets(cls) -> dict[str, Any]:
        # `system_prompt` is universal across LLMs — every transformer that
        # accepts it (chat-completions → role:system message; responses →
        # `instructions`) drops it cleanly when empty. Static widget on the
        # node so users don't need to add it via custom workflow tweaks.
        return {
            "system_prompt": ("STRING", {"default": "", "multiline": True}),
        }
