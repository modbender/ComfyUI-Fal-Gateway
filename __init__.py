"""ComfyUI-Fal-Gateway — package entry point.

Schema-driven gateway for fal.ai. Three nodes (T2V / I2V / Reference-to-Video)
that auto-populate from fal's model catalog. M1 ships a hardcoded MVP catalog;
M3 wires live fetch.

Imports are guarded so the package remains importable outside ComfyUI for
linting, packaging, and unit tests.
"""

WEB_DIRECTORY = "./web"
NODE_CLASS_MAPPINGS: dict = {}
NODE_DISPLAY_NAME_MAPPINGS: dict = {}

try:
    from server import PromptServer  # provided by ComfyUI runtime

    from .src.nodes import (
        NODE_CLASS_MAPPINGS as _NODE_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as _NODE_DISPLAY_NAME_MAPPINGS,
    )
    from .src.server_routes import register_routes

    NODE_CLASS_MAPPINGS = _NODE_CLASS_MAPPINGS
    NODE_DISPLAY_NAME_MAPPINGS = _NODE_DISPLAY_NAME_MAPPINGS
    register_routes(PromptServer.instance.routes)
except ImportError:
    # Outside ComfyUI runtime — node modules import fal_client/torch/cv2.
    pass


__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
]
