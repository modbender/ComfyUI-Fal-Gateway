"""Shared HTTP infrastructure for fal.ai API calls.

Used by `src/fal/catalog.py` and `src/fal/pricing.py`. Houses constants
(`FAL_API_BASE`, retry backoff, timeouts) and the auth-header builder
that both endpoints share.

Synchronous on purpose: catalog + pricing fire once at startup or on
manual refresh, never on the hot path. Async would force every caller
into async land.
"""

from __future__ import annotations

import ipaddress
import os
from urllib import request as urllib_request
from urllib.parse import urlparse


FAL_API_BASE = "https://api.fal.ai/v1"
DEFAULT_TIMEOUT_S = 20.0
MAX_PAGES = 100  # safety: avoid runaway loops in pagination walks
RETRY_BACKOFF_S = (1.0, 3.0, 8.0)  # progressive sleeps on 429

_PLACEHOLDER_KEY = "<your_fal_api_key_here>"

# Hostnames that resolve to loopback but aren't IP literals. We special-case
# these (cheap, zero-maintenance) since `localhost` is a common SSRF target.
_BLOCKED_HOSTNAMES = frozenset({"localhost", "localhost.localdomain"})


def validate_fetch_url(url: str) -> None:
    """Reject URLs unsafe to fetch (SSRF guard). Raises `ValueError` on reject.

    Blocklist approach (not an allowlist): fal rotates CDN domains, so an
    allowlist is high-maintenance. Instead we:
      - require an http/https scheme;
      - reject IP literals that are private, loopback, link-local, reserved,
        unspecified, or multicast (catches 127.x, 10.x, 192.168.x, the
        169.254.169.254 cloud-metadata endpoint, ::1, 0.0.0.0, etc.);
      - reject the `localhost` hostname family explicitly.

    Public hostnames (fal CDN domains) are allowed. We do NOT resolve DNS —
    DNS-rebinding is out of scope for this local-tool threat model.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"refusing to fetch non-http(s) URL: {url!r}")

    host = parsed.hostname
    if not host:
        raise ValueError(f"refusing to fetch URL with no host: {url!r}")

    if host.lower() in _BLOCKED_HOSTNAMES:
        raise ValueError(f"refusing to fetch loopback hostname: {host!r}")

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return  # not an IP literal — a hostname, allowed (no DNS resolution)

    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_unspecified
        or ip.is_multicast
    ):
        raise ValueError(f"refusing to fetch internal/reserved IP: {host!r}")


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
