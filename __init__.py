"""ComfyUI-Fal-Gateway — package entry point.

Schema-driven gateway for fal.ai exposing nine nodes (text/image/reference
for video + image, plus upscale, plus T2T and I2T). The dropdowns auto-
populate from fal's catalog (T2V/I2V/T2I/I2I/Ref/Upscale) or from a curated
flat catalog (T2T/I2T) — see `src/catalogs/`.
"""

import logging

WEB_DIRECTORY = "./web"
NODE_CLASS_MAPPINGS: dict = {}
NODE_DISPLAY_NAME_MAPPINGS: dict = {}

# Two-stage gate. The OUTER try only catches the "ComfyUI not present" case
# (we're being imported by linters / packagers / pytest). Once ComfyUI IS
# present, the inner imports run unguarded — any failure there is a real
# bug and must surface in ComfyUI's startup log instead of silently leaving
# NODE_CLASS_MAPPINGS empty (which presents as "node missing — install
# required" in the user's UI).
try:
    from server import PromptServer  # provided by ComfyUI runtime
except ImportError:
    # Outside ComfyUI — package stays importable but registers nothing.
    pass
else:
    try:
        from .src.nodes import (
            NODE_CLASS_MAPPINGS as _NODE_CLASS_MAPPINGS,
            NODE_DISPLAY_NAME_MAPPINGS as _NODE_DISPLAY_NAME_MAPPINGS,
        )
        from .src.routes import register_routes

        NODE_CLASS_MAPPINGS = _NODE_CLASS_MAPPINGS
        NODE_DISPLAY_NAME_MAPPINGS = _NODE_DISPLAY_NAME_MAPPINGS
        register_routes(PromptServer.instance.routes)
    except Exception:
        # Don't swallow silently — log first so the user sees WHY their nodes
        # are missing in ComfyUI's console, then re-raise so ComfyUI's own
        # custom-node loader shows the failure prominently in the UI.
        logging.getLogger("fal_gateway").exception(
            "Fal-Gateway failed to register nodes; check the traceback above."
        )
        raise


__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
]
