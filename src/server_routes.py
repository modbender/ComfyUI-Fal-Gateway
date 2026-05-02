"""HTTP routes for the Fal-Gateway.

POST /fal_gateway/refresh                Delete the on-disk catalog cache and kick off a
                                         background refetch. Returns 200 immediately.
GET  /fal_gateway/health                 Diagnostic: FAL_KEY presence + cached model count.
GET  /fal_gateway/schema/{model_id_b64}  Return the WidgetSpec list for a specific model
                                         (used by the frontend to render per-model widgets
                                         dynamically when the model dropdown changes).

Routes are registered against `PromptServer.instance.routes` in `__init__.py`.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import os

from aiohttp import web

from . import model_registry, pricing_cache


_log = logging.getLogger("fal_gateway.routes")
_PLACEHOLDER_KEY = "<your_fal_api_key_here>"


def decode_model_id_b64(b64: str) -> str:
    """URL-safe base64 → model_id, restoring stripped padding if needed.

    JavaScript's btoa() commonly outputs URL-safe base64 with padding stripped
    (per RFC 4648 §5 / §3.2). Python's `base64.urlsafe_b64decode` is strict
    about padding. This helper re-adds whatever padding is missing before
    decoding. Raises `ValueError` on truly invalid input.
    """
    padding_needed = (-len(b64)) % 4
    padded = b64 + ("=" * padding_needed)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid base64: {exc}") from exc


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

    @routes.get("/fal_gateway/schema/{model_id_b64}")
    async def get_schema(request: web.Request) -> web.Response:
        """Return parsed WidgetSpec list + shape for one model.

        The frontend hits this when the user changes the model dropdown so it can
        rebuild the per-model widgets (duration, aspect_ratio, resolution, seed,
        cfg_scale, negative_prompt, etc.) live without a ComfyUI restart.
        """
        b64 = request.match_info["model_id_b64"]
        try:
            model_id = decode_model_id_b64(b64)
        except ValueError:
            return web.json_response(
                {"ok": False, "error": "invalid base64 model_id"}, status=400
            )

        # `model_id` is a display string from the dropdown ("[provider] Name — id").
        try:
            entry = model_registry.resolve(model_id)
        except ValueError as exc:
            return web.json_response(
                {"ok": False, "error": f"malformed model_id: {exc}"}, status=400
            )
        if entry is None:
            return web.json_response(
                {"ok": False, "error": f"unknown model_id: {model_id}"}, status=404
            )

        # Trigger a background pricing refresh on first stale-cache schema
        # lookup. Subsequent requests during the in-flight refresh are no-ops.
        try:
            all_ids = [m.id for m in model_registry.all_models()]
            pricing_cache.trigger_refresh_if_stale(all_ids)
        except Exception as exc:  # noqa: BLE001 — best-effort
            _log.debug("pricing refresh trigger failed: %s", exc)

        return web.json_response(
            {
                "ok": True,
                "model_id": entry.id,
                "display_name": entry.display_name,
                "category": entry.category,
                "shape": entry.shape,
                "widgets": [w.to_dict() for w in entry.widgets],
                **pricing_cache.get_for_response(entry.id),
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

    @routes.post("/fal_gateway/pricing_refresh")
    async def refresh_pricing(request: web.Request) -> web.Response:
        """Clear pricing.json and trigger a fresh sweep. Used by the
        right-click "Fal-Gateway: refresh catalog cache" menu so the next
        schema lookup re-runs pricing fetch from scratch."""
        pricing_cache.clear()
        try:
            all_ids = [m.id for m in model_registry.all_models()]
            started = pricing_cache.trigger_refresh_if_stale(all_ids)
        except Exception as exc:  # noqa: BLE001
            return web.json_response(
                {"ok": False, "error": f"refresh trigger failed: {exc}"},
                status=500,
            )
        return web.json_response(
            {
                "ok": True,
                "started": started,
                "message": (
                    "Pricing cache cleared. A fresh fetch is running in the "
                    "background; cost labels will update when it completes."
                ),
            }
        )
