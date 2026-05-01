from __future__ import annotations

from .base import _FalGatewayNodeBase


class FalGatewayT2T(_FalGatewayNodeBase):
    CATEGORY_FILTER = "llm"
    SHAPE_FILTER = ()  # All LLMs are text-only; no shape filtering needed
    NODE_DISPLAY_LABEL = "Fal Text-to-Text"
    OUTPUT_KIND = "text"
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("response", "info")
