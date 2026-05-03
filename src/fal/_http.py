"""Shared HTTP infrastructure for fal.ai API calls.

Used by `src/fal/catalog.py` and `src/fal/pricing.py`. Houses constants
(`FAL_API_BASE`, retry backoff, timeouts) and the auth-header builder
that both endpoints share.

Synchronous on purpose: catalog + pricing fire once at startup or on
manual refresh, never on the hot path. Async would force every caller
into async land.
"""

from __future__ import annotations

import os
from urllib import request as urllib_request


FAL_API_BASE = "https://api.fal.ai/v1"
DEFAULT_TIMEOUT_S = 20.0
MAX_PAGES = 100  # safety: avoid runaway loops in pagination walks
RETRY_BACKOFF_S = (1.0, 3.0, 8.0)  # progressive sleeps on 429

_PLACEHOLDER_KEY = "<your_fal_api_key_here>"


def build_request(url: str) -> urllib_request.Request:
    """Build a urllib Request with `Authorization: Key <FAL_KEY>` if available.

    The catalog endpoint is publicly readable but auth raises rate limits.
    The pricing endpoint requires auth.
    """
    headers = {
        "Accept": "application/json",
        "User-Agent": "ComfyUI-Fal-Gateway/0.1",
    }
    key = os.environ.get("FAL_KEY")
    if key and key != _PLACEHOLDER_KEY:
        headers["Authorization"] = f"Key {key}"
    return urllib_request.Request(url, headers=headers)
