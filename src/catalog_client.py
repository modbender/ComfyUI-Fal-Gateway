"""Fetch fal.ai's model catalog via the public REST endpoint.

Endpoint: GET https://api.fal.ai/v1/models
Filters: category=text-to-video / image-to-video / etc.
Pagination: cursor-based via `next_cursor` + `has_more`.
Auth: optional. We send `Authorization: Key <FAL_KEY>` if available — the
catalog is publicly readable but auth raises rate limits.

Synchronous on purpose: this fires once at ComfyUI startup; an async path
would force the caller to be async too, complicating module init.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request


_log = logging.getLogger("fal_gateway.catalog")

FAL_API_BASE = "https://api.fal.ai/v1"
CATALOG_URL = f"{FAL_API_BASE}/models"
PRICING_URL = f"{FAL_API_BASE}/models/pricing"
DEFAULT_TIMEOUT_S = 20.0
DEFAULT_PAGE_LIMIT = 50  # used when with_schemas=False; the API rejects 50 with schemas
SCHEMA_PAGE_LIMIT = 10  # API caps page size at ~10 when expand=openapi-3.0
PRICING_BATCH_SIZE = 50  # max endpoint_ids per pricing request
MAX_PAGES = 100  # safety: avoid runaway loops
RETRY_BACKOFF_S = (1.0, 3.0, 8.0)  # progressive sleeps on 429


def _build_request(url: str) -> urllib_request.Request:
    headers = {
        "Accept": "application/json",
        "User-Agent": "ComfyUI-Fal-Gateway/0.1",
    }
    key = os.environ.get("FAL_KEY")
    if key and key != "<your_fal_api_key_here>":
        headers["Authorization"] = f"Key {key}"
    return urllib_request.Request(url, headers=headers)


def _fetch_page(
    category: str | None,
    cursor: str | None,
    limit: int,
    timeout_s: float,
    with_schemas: bool = False,
) -> dict[str, Any]:
    params: dict[str, str] = {"limit": str(limit)}
    if category is not None:
        params["category"] = category
    if cursor is not None:
        params["cursor"] = cursor
    if with_schemas:
        params["expand"] = "openapi-3.0"
    url = f"{CATALOG_URL}?{urllib_parse.urlencode(params)}"
    req = _build_request(url)
    with urllib_request.urlopen(req, timeout=timeout_s) as response:
        body = response.read()
    return json.loads(body)


def fetch_all_models(
    category: str | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    limit: int | None = None,
    with_schemas: bool = False,
) -> list[dict[str, Any]]:
    if limit is None:
        limit = SCHEMA_PAGE_LIMIT if with_schemas else DEFAULT_PAGE_LIMIT
    """Walk all pages of fal's model catalog. Returns raw model dicts.

    Each entry has shape:
      {
        "endpoint_id": "<fal-id>",
        "metadata": {
          "display_name": "...",
          "category": "image-to-video",
          "description": "...",
          "status": "active",
          "tags": [...],
          ...
        }
      }
    """
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    for page_idx in range(MAX_PAGES):
        page = _fetch_page_with_retries(category, cursor, limit, timeout_s, with_schemas)
        if page is None:
            _log.warning(
                "catalog page %d gave up after retries; returning %d partial entries",
                page_idx,
                len(out),
            )
            break
        models = page.get("models", [])
        out.extend(models)
        if not page.get("has_more"):
            break
        cursor = page.get("next_cursor")
        if not cursor:
            break
    _log.info(
        "fetched %d catalog entries (category=%s, pages walked=%d)",
        len(out),
        category or "all",
        page_idx + 1,
    )
    return out


def _fetch_page_with_retries(
    category: str | None,
    cursor: str | None,
    limit: int,
    timeout_s: float,
    with_schemas: bool,
) -> dict[str, Any] | None:
    last_err: Exception | None = None
    for attempt, backoff in enumerate((0.0,) + RETRY_BACKOFF_S):
        if backoff > 0:
            time.sleep(backoff)
        try:
            return _fetch_page(category, cursor, limit, timeout_s, with_schemas=with_schemas)
        except urllib_error.HTTPError as exc:
            last_err = exc
            if exc.code == 429:
                _log.info("rate-limited (429) on attempt %d; backing off", attempt + 1)
                continue
            _log.warning("catalog page failed (HTTP %d): %s", exc.code, exc)
            return None
        except (urllib_error.URLError, TimeoutError) as exc:
            last_err = exc
            _log.warning("catalog page network error on attempt %d: %s", attempt + 1, exc)
            continue
    _log.warning("catalog page exhausted retries: %s", last_err)
    return None


_DEFAULT_CATEGORIES = (
    "text-to-video",
    "image-to-video",
    "text-to-image",
    "image-to-image",
    "llm",
    "vision",
)


def fetch_active_video_models(
    timeout_s: float = DEFAULT_TIMEOUT_S,
    with_schemas: bool | None = None,
    categories: tuple[str, ...] = _DEFAULT_CATEGORIES,
) -> dict[str, list[dict[str, Any]]]:
    """Convenience wrapper: pull catalogs for the named fal categories.

    Returns a dict keyed by category, e.g. {"text-to-video": [...], ...}, each
    holding the active models in that category.

    Default categories cover video + image (T2V/I2V/T2I/I2I). Pass an explicit
    tuple to narrow scope (e.g. for tests).

    `with_schemas`:
      - True  → fetch with OpenAPI schemas embedded (slower, more accurate widgets;
                requires FAL_KEY for sane rate limits).
      - False → metadata only (fast; widget specs synthesized from category).
      - None (default) → True if FAL_KEY is set, else False. Safe auto-mode.
    """
    if with_schemas is None:
        key = os.environ.get("FAL_KEY")
        with_schemas = bool(key) and key != "<your_fal_api_key_here>"

    out: dict[str, list[dict[str, Any]]] = {}
    for category in categories:
        try:
            raw = fetch_all_models(
                category=category, timeout_s=timeout_s, with_schemas=with_schemas
            )
        except Exception as exc:  # noqa: BLE001 — caller decides how to recover
            _log.warning("could not fetch category=%s: %s", category, exc)
            out[category] = []
            continue
        active = [
            m for m in raw if (m.get("metadata") or {}).get("status", "active") == "active"
        ]
        out[category] = active
    return out


# --------------------------------------------------------------------------
# Pricing — /v1/models/pricing batched lookup.
#
# The pricing endpoint accepts up to PRICING_BATCH_SIZE endpoint_ids per call
# and requires authentication. Response shapes observed at fal vary slightly
# (`prices` vs `models` envelope keys); both are accepted by `_extract_prices`.
# Returns a dict keyed by endpoint_id so consumers can do O(1) lookup while
# building ModelEntry objects.
# --------------------------------------------------------------------------


def _extract_prices(page: dict[str, Any]) -> list[dict[str, Any]]:
    """Tolerantly pull the price-list array from a pricing API response.

    Known/anticipated envelope keys: `prices`, `models`, `data`. Falls back
    to the page itself if it's already a list (some APIs do that).
    """
    if isinstance(page, list):
        return page
    for key in ("prices", "models", "data"):
        items = page.get(key)
        if isinstance(items, list):
            return items
    return []


def _normalize_price_entry(item: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Map one pricing record → (endpoint_id, {unit_price, unit, currency}).

    Returns None when the entry is missing an endpoint_id. Tolerates a few
    field-name variants (`unit_price` vs `price`, `unit` vs `pricing_unit`).
    """
    endpoint_id = item.get("endpoint_id") or item.get("id")
    if not endpoint_id:
        return None
    raw_price = item.get("unit_price")
    if raw_price is None:
        raw_price = item.get("price")
    try:
        unit_price = float(raw_price) if raw_price is not None else None
    except (TypeError, ValueError):
        unit_price = None
    unit = item.get("unit") or item.get("pricing_unit")
    currency = item.get("currency") or "USD"
    return str(endpoint_id), {
        "unit_price": unit_price,
        "unit": str(unit) if unit else None,
        "currency": str(currency) if currency else None,
    }


def _fetch_pricing_page(
    endpoint_ids: list[str],
    cursor: str | None,
    timeout_s: float,
) -> dict[str, Any]:
    params: dict[str, str] = {"endpoint_id": ",".join(endpoint_ids)}
    if cursor is not None:
        params["cursor"] = cursor
    url = f"{PRICING_URL}?{urllib_parse.urlencode(params)}"
    req = _build_request(url)
    with urllib_request.urlopen(req, timeout=timeout_s) as response:
        body = response.read()
    return json.loads(body)


def _fetch_pricing_page_with_retries(
    endpoint_ids: list[str],
    cursor: str | None,
    timeout_s: float,
) -> dict[str, Any] | None:
    """Same retry/backoff shape as `_fetch_page_with_retries` but for pricing.

    Returns None on non-recoverable failures (401/403/etc.) so the caller can
    log and continue with no pricing data — degraded UX, not a crash.
    """
    last_err: Exception | None = None
    for attempt, backoff in enumerate((0.0,) + RETRY_BACKOFF_S):
        if backoff > 0:
            time.sleep(backoff)
        try:
            return _fetch_pricing_page(endpoint_ids, cursor, timeout_s)
        except urllib_error.HTTPError as exc:
            last_err = exc
            if exc.code == 429:
                _log.info("pricing rate-limited (429) on attempt %d; backing off", attempt + 1)
                continue
            _log.warning("pricing fetch failed (HTTP %d): %s", exc.code, exc)
            return None
        except (urllib_error.URLError, TimeoutError) as exc:
            last_err = exc
            _log.warning("pricing network error on attempt %d: %s", attempt + 1, exc)
            continue
    _log.warning("pricing fetch exhausted retries: %s", last_err)
    return None


def fetch_all_pricing(
    endpoint_ids: list[str],
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict[str, dict[str, Any]]:
    """Batch-fetch pricing for every endpoint_id in `endpoint_ids`.

    Walks the pricing API in batches of `PRICING_BATCH_SIZE`, then walks any
    `next_cursor` pagination within each batch (rare — fal usually returns
    every requested id in one page, but we honour cursor if present).

    Returns `{endpoint_id: {"unit_price": float|None, "unit": str|None,
    "currency": str|None}}`. Endpoints not returned by fal are simply absent
    from the dict; callers should treat absence as "pricing unknown".

    Failures (auth, rate-limit-after-retries, network) log a warning and
    return whatever was successfully fetched (possibly an empty dict). The
    cost-widget downstream falls back to "Pricing unavailable".
    """
    out: dict[str, dict[str, Any]] = {}
    if not endpoint_ids:
        return out
    deduped: list[str] = list(dict.fromkeys(endpoint_ids))
    for start in range(0, len(deduped), PRICING_BATCH_SIZE):
        batch = deduped[start : start + PRICING_BATCH_SIZE]
        cursor: str | None = None
        for _page_idx in range(MAX_PAGES):
            page = _fetch_pricing_page_with_retries(batch, cursor, timeout_s)
            if page is None:
                break
            for item in _extract_prices(page):
                if not isinstance(item, dict):
                    continue
                normalized = _normalize_price_entry(item)
                if normalized is None:
                    continue
                key, payload = normalized
                out[key] = payload
            if not page.get("has_more"):
                break
            cursor = page.get("next_cursor")
            if not cursor:
                break
    _log.info(
        "fetched pricing for %d / %d endpoints",
        len(out),
        len(deduped),
    )
    return out
