from __future__ import annotations

from .base import _FalGatewayNodeBase


class FalUpscale(_FalGatewayNodeBase):
    CATEGORY_FILTER = "image-to-image"
    SHAPE_FILTER = ("upscale",)
    NODE_DISPLAY_LABEL = "Fal Upscale"
    OUTPUT_KIND = "image"
    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "image_url", "info")

    @classmethod
    def image_socket_names(cls) -> tuple[str, ...]:
        return ("image",)
