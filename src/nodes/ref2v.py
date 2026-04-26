from __future__ import annotations

from typing import Any

from .base import _FalGatewayNodeBase


class FalGatewayRef2V(_FalGatewayNodeBase):
    CATEGORY_FILTER = "image-to-video"
    SHAPE_FILTER = ("flf", "multi_ref")
    NODE_DISPLAY_LABEL = "Fal Reference-to-Video"

    @classmethod
    def image_socket_names(cls) -> tuple[str, ...]:
        # image_1 always required.
        return ("image_1",)

    @classmethod
    def optional_image_socket_names(cls) -> tuple[str, ...]:
        # image_2..4 declared as max; the frontend extension shows/hides them
        # based on the `image_count` widget value (1..4). Only the visible ones
        # appear in node.inputs at queue-time, so the backend only receives those.
        return ("image_2", "image_3", "image_4")

    @classmethod
    def extra_required_widgets(cls) -> dict[str, Any]:
        return {
            "image_count": ("INT", {"default": 2, "min": 1, "max": 4, "step": 1}),
        }
