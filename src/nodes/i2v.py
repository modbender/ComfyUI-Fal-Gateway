from __future__ import annotations

from .base import _FalGatewayNodeBase


class FalGatewayI2V(_FalGatewayNodeBase):
    CATEGORY_FILTER = "image-to-video"
    # Include FLF-capable models too — they work as plain I2V when only the
    # start image is wired (end_image_url is optional in their schemas).
    SHAPE_FILTER = ("single_image", "flf")
    NODE_DISPLAY_LABEL = "Fal Image-to-Video"

    @classmethod
    def image_socket_names(cls) -> tuple[str, ...]:
        return ("image",)
