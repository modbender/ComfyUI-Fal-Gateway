from __future__ import annotations

from .base import _FalGatewayNodeBase


class FalGatewayT2V(_FalGatewayNodeBase):
    CATEGORY_FILTER = "text-to-video"
    SHAPE_FILTER = ("text_only",)
    NODE_DISPLAY_LABEL = "Fal Text-to-Video"
