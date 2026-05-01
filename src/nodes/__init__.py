"""Node class aggregator for ComfyUI-Fal-Gateway.

Single source of truth: `_NODES` is a registry of (registry_key, class, display_name)
triples. Both NODE_CLASS_MAPPINGS and NODE_DISPLAY_NAME_MAPPINGS derive from it,
so adding a new node is a one-line entry rather than three parallel edits.
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
    from .upscale import FalGatewayUpscale
    from .t2t import FalGatewayT2T
    from .i2t import FalGatewayI2T

    _NODES: tuple[tuple[str, type, str], ...] = (
        ("FalGatewayT2V",     FalGatewayT2V,     "Fal Text-to-Video"),
        ("FalGatewayI2V",     FalGatewayI2V,     "Fal Image-to-Video"),
        ("FalGatewayRef2V",   FalGatewayRef2V,   "Fal Reference-to-Video"),
        ("FalGatewayT2I",     FalGatewayT2I,     "Fal Text-to-Image"),
        ("FalGatewayI2I",     FalGatewayI2I,     "Fal Image-to-Image"),
        ("FalGatewayRef2I",   FalGatewayRef2I,   "Fal Reference-to-Image"),
        ("FalGatewayUpscale", FalGatewayUpscale, "Fal Upscale"),
        ("FalGatewayT2T",     FalGatewayT2T,     "Fal Text-to-Text"),
        ("FalGatewayI2T",     FalGatewayI2T,     "Fal Image-to-Text"),
    )

    NODE_CLASS_MAPPINGS = {key: cls for key, cls, _name in _NODES}
    NODE_DISPLAY_NAME_MAPPINGS = {key: name for key, _cls, name in _NODES}
except ImportError:
    # Outside ComfyUI runtime — node modules import comfy/torch/etc.; tests skip this.
    pass
