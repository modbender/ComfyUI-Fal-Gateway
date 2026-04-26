"""HTTP routes for the Fal-Gateway.

POST /fal_gateway/refresh   Delete the on-disk catalog cache and kick off a
                            background refetch. Returns 200 immediately —
                            the refetch progresses asynchronously.
GET  /fal_gateway/health    Diagnostic: FAL_KEY presence + cached model count.

Routes are registered against `PromptServer.instance.routes` in `__init__.py`.
"""

from __future__ import annotations

import asyncio
import logging
import os

from aiohttp import web

from . import model_registry


_log = logging.getLogger("fal_gateway.routes")
_PLACEHOLDER_KEY = "<your_fal_api_key_here>"


def register_routes(routes: web.RouteTableDef) -> None:
    @routes.post("/fal_gateway/refresh")
    async def refresh_catalog(request: web.Request) -> web.Response:
        cache_path = model_registry._CACHE_PATH  # noqa: SLF001 — internal access by design
        deleted = False
        if cache_path.exists():
            try:
                cache_path.unlink()
                deleted = True
            except OSError as exc:
                _log.warning("could not delete cache file %s: %s", cache_path, exc)
                return web.json_response(
                    {"ok": False, "error": f"could not delete cache: {exc}"},
                    status=500,
                )

        model_registry.reload()

        # Kick off a refetch in a worker thread so the next ComfyUI restart
        # finds a warm cache. We don't block the response on it.
        loop = asyncio.get_running_loop()

        def _warm_cache() -> int:
            try:
                return len(model_registry.all_models())
            except Exception as exc:  # noqa: BLE001
                _log.warning("background refetch failed: %s", exc)
                return -1

        loop.run_in_executor(None, _warm_cache)

        return web.json_response(
            {
                "ok": True,
                "deleted": deleted,
                "message": (
                    "Cache cleared. A fresh fetch has started in the background. "
                    "Restart ComfyUI to see the updated model dropdowns "
                    "(existing placed nodes keep their old dropdown options "
                    "until you re-add them or restart)."
                ),
            }
        )

    @routes.get("/fal_gateway/health")
    async def health(request: web.Request) -> web.Response:
        key = os.environ.get("FAL_KEY")
        key_set = bool(key) and key != _PLACEHOLDER_KEY
        try:
            count = len(model_registry.all_models())
        except Exception:  # noqa: BLE001
            count = -1
        return web.json_response(
            {"fal_key_present": key_set, "model_count": count}
        )
