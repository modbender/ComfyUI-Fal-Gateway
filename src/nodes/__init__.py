"""Node class aggregator for ComfyUI-Fal-Gateway.

Imports the seven node classes (3 video + 4 image) and exposes them via
NODE_CLASS_MAPPINGS so the top-level package __init__.py can register them
with ComfyUI.
"""

from __future__ import annotations

NODE_CLASS_MAPPINGS: dict = {}
NODE_DISPLAY_NAME_MAPPINGS: dict = {}

try:
    from .t2v import FalGatewayT2V
    from .i2v import FalGatewayI2V
    from .ref2v import FalGatewayRef2V
    from .t2i import FalGatewayT2I
    from .i2i import FalGatewayI2I
    from .ref2i import FalGatewayRef2I
    from .upscale import FalUpscale

    NODE_CLASS_MAPPINGS = {
        "FalGatewayT2V": FalGatewayT2V,
        "FalGatewayI2V": FalGatewayI2V,
        "FalGatewayRef2V": FalGatewayRef2V,
        "FalGatewayT2I": FalGatewayT2I,
        "FalGatewayI2I": FalGatewayI2I,
        "FalGatewayRef2I": FalGatewayRef2I,
        "FalUpscale": FalUpscale,
    }
    NODE_DISPLAY_NAME_MAPPINGS = {
        "FalGatewayT2V": "Fal Text-to-Video",
        "FalGatewayI2V": "Fal Image-to-Video",
        "FalGatewayRef2V": "Fal Reference-to-Video",
        "FalGatewayT2I": "Fal Text-to-Image",
        "FalGatewayI2I": "Fal Image-to-Image",
        "FalGatewayRef2I": "Fal Reference-to-Image",
        "FalUpscale": "Fal Upscale",
    }
except ImportError:
    # Outside ComfyUI runtime — node modules import comfy/torch/etc.; tests skip this.
    pass
