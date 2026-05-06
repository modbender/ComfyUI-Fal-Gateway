"""Fetch OpenRouter's model catalog.

Endpoint: GET https://openrouter.ai/api/v1/models  (no auth required for the list)

Each catalog entry includes `architecture.input_modalities` — the authoritative
"does this model accept image input?" signal. We filter on that field and
return a list of dicts the caller (catalogs/i2t.py) turns into CatalogEntry
rows pointing at the fal endpoint `openrouter/router/vision`.

Synchronous + stdlib `urllib` to mirror src/fal/catalog.py's style and avoid
async-init-time complications.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request


_log = logging.getLogger("fal_gateway.openrouter")

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
DEFAULT_TIMEOUT_S = 10.0
RETRY_BACKOFF_S = (0.5, 2.0)


def _fetch_raw(timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """One HTTP GET → parsed JSON dict. Raises OSError on network failure."""
    req = urllib_request.Request(
        OPENROUTER_MODELS_URL,
        headers={"User-Agent": "comfyui-fal-gateway/1.0"},
    )
    with urllib_request.urlopen(req, timeout=timeout_s) as response:
        body = response.read()
    return json.loads(body)


def parse_models_response(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise the response into our minimal shape: {id, name, input_modalities, description}."""
    out: list[dict[str, Any]] = []
    for entry in raw.get("data") or []:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        if not model_id:
            continue
        arch = entry.get("architecture") or {}
        modalities = arch.get("input_modalities") or []
        if not isinstance(modalities, list):
            modalities = []
        out.append({
            "id": str(model_id),
            "name": str(entry.get("name") or model_id),
            "input_modalities": [str(m) for m in modalities if isinstance(m, str)],
            "description": str(entry.get("description") or ""),
        })
    return out


def filter_vision_capable(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep models whose input_modalities includes 'image'."""
    return [m for m in models if "image" in (m.get("input_modalities") or [])]


def fetch_vision_models(timeout_s: float = DEFAULT_TIMEOUT_S) -> list[dict[str, Any]]:
    """Fetch + parse + filter. Returns empty list on any failure (logged)."""
    last_err: Exception | None = None
    for attempt, backoff in enumerate((0.0,) + RETRY_BACKOFF_S):
        if backoff > 0:
            time.sleep(backoff)
        try:
            raw = _fetch_raw(timeout_s=timeout_s)
            return filter_vision_capable(parse_models_response(raw))
        except (urllib_error.URLError, urllib_error.HTTPError, TimeoutError, OSError) as exc:
            last_err = exc
            _log.warning("openrouter fetch attempt %d failed: %s", attempt + 1, exc)
            continue
    _log.warning("openrouter fetch exhausted retries: %s", last_err)
    return []
