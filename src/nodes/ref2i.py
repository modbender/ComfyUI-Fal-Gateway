from __future__ import annotations

from typing import Any

from .base import _FalGatewayNodeBase


class FalGatewayRef2I(_FalGatewayNodeBase):
    CATEGORY_FILTER = "image-to-image"
    SHAPE_FILTER = ("flf", "multi_ref")
    NODE_DISPLAY_LABEL = "Fal Reference-to-Image"
    OUTPUT_KIND = "image"
    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "image_url", "info")

    @classmethod
    def image_socket_names(cls) -> tuple[str, ...]:
        return ("image_1",)

    @classmethod
    def optional_image_socket_names(cls) -> tuple[str, ...]:
        return ("image_2", "image_3", "image_4")

    @classmethod
    def extra_required_widgets(cls) -> dict[str, Any]:
        return {
            "image_count": ("INT", {"default": 2, "min": 1, "max": 4, "step": 1}),
        }
