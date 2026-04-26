from __future__ import annotations

from .base import _FalGatewayNodeBase


class FalGatewayT2I(_FalGatewayNodeBase):
    CATEGORY_FILTER = "text-to-image"
    SHAPE_FILTER = ("text_only",)
    NODE_DISPLAY_LABEL = "Fal Text-to-Image"
    OUTPUT_KIND = "image"
    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "image_url", "info")
