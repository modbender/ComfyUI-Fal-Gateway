from __future__ import annotations

from .base import _FalGatewayNodeBase


class FalGatewayI2I(_FalGatewayNodeBase):
    CATEGORY_FILTER = "image-to-image"
    # Include FLF-capable models too — they work as plain I2I when only the
    # start image is wired (end_image_url is optional in their schemas).
    SHAPE_FILTER = ("single_image", "flf")
    NODE_DISPLAY_LABEL = "Fal Image-to-Image"
    OUTPUT_KIND = "image"
    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "image_url", "info")

    @classmethod
    def image_socket_names(cls) -> tuple[str, ...]:
        return ("image",)
