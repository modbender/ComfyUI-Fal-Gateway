"""ComfyUI-Fal-Gateway — package entry point.

Schema-driven gateway for fal.ai exposing ten nodes (text/image/reference
for video + image, plus upscale, plus T2T, I2T, and JSON Extract). The
dropdowns auto-populate from fal's catalog (T2V/I2V/T2I/I2I/Ref/Upscale)
or from a curated flat catalog (T2T/I2T) — see `src/catalogs/`.
"""

import logging

WEB_DIRECTORY = "./web"
NODE_CLASS_MAPPINGS: dict = {}
NODE_DISPLAY_NAME_MAPPINGS: dict = {}

# Node mappings are populated unconditionally — the node modules don't
# depend on ComfyUI's runtime to be importable. This matters for the
# Comfy Registry indexer (registry.comfy.org), which imports the package
# without ComfyUI present to scrape NODE_CLASS_MAPPINGS for the search
# index. If the import fails for some genuine bug, log it visibly but
# don't crash linters/packagers/the registry.
try:
    from .src.nodes import (
        NODE_CLASS_MAPPINGS as _NODE_CLASS_MAPPINGS,
        NODE_DISPLAY_NAME_MAPPINGS as _NODE_DISPLAY_NAME_MAPPINGS,
    )

    NODE_CLASS_MAPPINGS = _NODE_CLASS_MAPPINGS
    NODE_DISPLAY_NAME_MAPPINGS = _NODE_DISPLAY_NAME_MAPPINGS
except Exception:
    logging.getLogger("fal_gateway").exception(
        "Fal-Gateway: failed to load node mappings; nodes will not appear."
    )

# HTTP routes only register inside the ComfyUI runtime — they need
# `server.PromptServer.instance`. Outside ComfyUI (linters, packagers,
# the registry indexer) this block is skipped silently.
try:
    from server import PromptServer  # provided by ComfyUI runtime

    from .src.routes import register_routes

    register_routes(PromptServer.instance.routes)
except ImportError:
    # `server` not present — not running inside ComfyUI. Nothing to do.
    pass
except Exception:
    logging.getLogger("fal_gateway").exception(
        "Fal-Gateway: route registration failed inside ComfyUI runtime."
    )
    raise


__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
]
