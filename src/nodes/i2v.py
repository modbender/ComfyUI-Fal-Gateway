from __future__ import annotations

from .base import _FalGatewayNodeBase


class FalGatewayI2V(_FalGatewayNodeBase):
    CATEGORY_FILTER = "image-to-video"
    SHAPE_FILTER = ("single_image",)
    NODE_DISPLAY_LABEL = "Fal Image-to-Video"

    @classmethod
    def image_socket_names(cls) -> tuple[str, ...]:
        return ("image",)
