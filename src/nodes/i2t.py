from __future__ import annotations

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
