"""Model registry — merges live fal.ai catalog with the bundled fallback.

Lookup order on first access:
  1. `cache/catalog.json` if present and < CACHE_TTL_DAYS old (fast warm path).
  2. Live fetch via `catalog_client.fetch_active_video_models()` (blocks once, then
     written to cache for subsequent restarts).
  3. `src/fallback_catalog.json` (bundled, offline-bootable last resort).

Hardcoded entries from the bundled fallback override live entries of the same
endpoint id — that lets us ship better-than-default widget specs for the
common-known models (Seedance, Kling, MiniMax) while still surfacing the
hundreds of models we haven't hand-curated.

For live entries without curated widget specs, we synthesize a minimal spec
from the model's category (`text-to-video` → `[prompt]`; `image-to-video` →
`[prompt, image→image_url]`). M2 will replace synthesis with real OpenAPI
parsing.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import catalog_client
from .schema_resolver import SchemaError, parse_openapi
from .widget_spec import ModelEntry, WidgetSpec


_log = logging.getLogger("fal_gateway.registry")

_PKG_DIR = Path(__file__).resolve().parent
_FALLBACK_PATH = _PKG_DIR / "fallback_catalog.json"
_CACHE_PATH = _PKG_DIR.parent / "cache" / "catalog.json"

CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days
SCHEMA_VERSION = 4  # bump when WidgetSpec format changes OR new fal categories are
                    # added to the fetched set, so existing caches are invalidated
                    # and refetched with the new category coverage. Last bumps:
                    #   1 → 2: added text-to-image + image-to-image categories
                    #   2 → 3: added llm + vision categories (v0.3.0)
                    #   3 → 4: added pricing fields (unit_price/unit/currency)

_lock = threading.Lock()
_models: list[ModelEntry] | None = None


def _load_fallback() -> list[ModelEntry]:
    with open(_FALLBACK_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return [ModelEntry.from_dict(m) for m in data.get("models", [])]


def _load_cache_if_fresh() -> list[ModelEntry] | None:
    if not _CACHE_PATH.exists():
        return None
    try:
        age = time.time() - _CACHE_PATH.stat().st_mtime
        if age > CACHE_TTL_SECONDS:
            _log.info("cached catalog is stale (%.1f days old); refetching", age / 86400)
            return None
        with open(_CACHE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("schema_version") != SCHEMA_VERSION:
            _log.info(
                "cache schema_version %s != %s; refetching",
                data.get("schema_version"),
                SCHEMA_VERSION,
            )
            return None
        models = [ModelEntry.from_dict(m) for m in data.get("models", [])]
        _log.info("loaded %d models from cache (age %.1f hours)", len(models), age / 3600)
        return models
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning("cache read failed: %s", exc)
        return None


def _write_cache(models: list[ModelEntry]) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CACHE_PATH.with_suffix(".tmp")
        payload = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": SCHEMA_VERSION,
            "models": [m.to_dict() for m in models],
        }
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        tmp.replace(_CACHE_PATH)
        _log.info("wrote %d models to %s", len(models), _CACHE_PATH)
    except OSError as exc:
        _log.warning("cache write failed: %s", exc)


# Single source of truth for category-level fal taxonomy. Adding a new category
# is one row here — `_synthesize_widgets`, `_shape_from_category`, and
# `_ACCEPTED_CATEGORIES` all derive from this map.
_CATEGORY_CONFIG: dict[str, dict[str, Any]] = {
    "text-to-video":  {"shape": "text_only",    "needs_image": False},
    "image-to-video": {"shape": "single_image", "needs_image": True},
    "text-to-image":  {"shape": "text_only",    "needs_image": False},
    "image-to-image": {"shape": "single_image", "needs_image": True},
    "llm":            {"shape": "text_only",    "needs_image": False},
    "vision":         {"shape": "text_only",    "needs_image": True},
}

_ACCEPTED_CATEGORIES = tuple(_CATEGORY_CONFIG.keys())


def _synthesize_widgets(category: str) -> list[WidgetSpec]:
    """Default widget set for a model with no curated spec. Used as a fallback when
    the OpenAPI schema is unavailable (no-key cold-start, parse errors)."""
    cfg = _CATEGORY_CONFIG.get(category, {})
    base = [
        WidgetSpec(
            name="prompt",
            kind="STRING",
            default="",
            required=True,
            multiline=True,
            payload_key="prompt",
        ),
    ]
    if cfg.get("needs_image"):
        base.append(
            WidgetSpec(
                name="image",
                kind="IMAGE_INPUT",
                required=True,
                payload_key="image_url",
            )
        )
    return base


def _shape_from_category(category: str) -> str:
    """Best-effort shape inference without OpenAPI."""
    return _CATEGORY_CONFIG.get(category, {}).get("shape", "text_only")


def _entry_from_raw(
    raw: dict[str, Any],
    pricing: dict[str, dict[str, Any]] | None = None,
) -> ModelEntry | None:
    endpoint_id = raw.get("endpoint_id")
    if not endpoint_id:
        return None
    metadata = raw.get("metadata") or {}
    category = metadata.get("category", "")
    if category not in _ACCEPTED_CATEGORIES:
        return None
    if metadata.get("status", "active") != "active":
        return None
    display = metadata.get("display_name") or endpoint_id
    description = metadata.get("description") or ""

    # Prefer OpenAPI-driven widgets when the schema is embedded.
    widgets: list[WidgetSpec]
    shape: str
    openapi = raw.get("openapi")
    if isinstance(openapi, dict) and openapi:
        try:
            parsed = parse_openapi(
                openapi, category, metadata=metadata, endpoint_id=str(endpoint_id)
            )
            widgets = parsed.widgets
            shape = parsed.shape
        except SchemaError as exc:
            _log.debug("schema parse failed for %s: %s — falling back to synth", endpoint_id, exc)
            widgets = _synthesize_widgets(category)
            shape = _shape_from_category(category)
    else:
        widgets = _synthesize_widgets(category)
        shape = _shape_from_category(category)

    price_info = (pricing or {}).get(str(endpoint_id)) or {}
    return ModelEntry(
        id=str(endpoint_id),
        display_name=str(display),
        category=str(category),
        shape=shape,
        description=str(description),
        widgets=widgets,
        unit_price=price_info.get("unit_price"),
        unit=price_info.get("unit"),
        currency=price_info.get("currency"),
    )


def _live_fetch() -> list[ModelEntry] | None:
    try:
        per_category = catalog_client.fetch_active_video_models()
    except Exception as exc:  # noqa: BLE001 — fall through to fallback
        _log.warning("live catalog fetch failed: %s", exc)
        return None

    # Pull pricing for every active endpoint in one batched pass. Failures
    # (missing FAL_KEY, rate-limit-after-retries) degrade gracefully — the
    # cost-label widget falls back to "Pricing unavailable".
    all_endpoint_ids = [
        str(raw.get("endpoint_id"))
        for raws in per_category.values()
        for raw in raws
        if raw.get("endpoint_id")
    ]
    try:
        pricing = catalog_client.fetch_all_pricing(all_endpoint_ids)
    except Exception as exc:  # noqa: BLE001 — pricing is best-effort
        _log.warning("pricing fetch failed: %s — proceeding without pricing", exc)
        pricing = {}

    out: list[ModelEntry] = []
    for category, raw_list in per_category.items():
        for raw in raw_list:
            entry = _entry_from_raw(raw, pricing=pricing)
            if entry is not None:
                out.append(entry)
    if not out:
        return None
    return out


def _merge(curated: list[ModelEntry], live: list[ModelEntry]) -> list[ModelEntry]:
    """Curated entries win for the same id; live fills the rest."""
    by_id: dict[str, ModelEntry] = {m.id: m for m in live}
    for m in curated:
        by_id[m.id] = m  # override / add
    return list(by_id.values())


def _do_load() -> list[ModelEntry]:
    fallback = _load_fallback()

    cached = _load_cache_if_fresh()
    if cached is not None:
        return _merge(fallback, cached)

    live = _live_fetch()
    if live is not None:
        merged = _merge(fallback, live)
        _write_cache(merged)
        return merged

    _log.info("falling back to bundled %d-model catalog", len(fallback))
    return fallback


def _load() -> list[ModelEntry]:
    global _models
    with _lock:
        if _models is not None:
            return _models
        _models = _do_load()
        return _models


def reload() -> None:
    """Drop the cached catalog so next access re-fetches. Test seam + manual refresh."""
    global _models
    with _lock:
        _models = None


def all_models() -> list[ModelEntry]:
    return list(_load())


def get(model_id: str) -> ModelEntry | None:
    for m in _load():
        if m.id == model_id:
            return m
    return None


import re as _re

# Per-category endpoint-id exclude patterns. fal's `llm` category is a grab-bag
# that includes embeddings + moderation + chat models under one label. We drop
# the not-actually-text-generation endpoints here so they don't pollute T2T.
# Adding a new exclusion = one entry.
_CATEGORY_EXCLUDE_PATTERNS: dict[str, "_re.Pattern[str]"] = {
    "llm": _re.compile(r"/embeddings?$", _re.IGNORECASE),
}


def filter_models(category: str, shapes: tuple[str, ...] | None = None) -> list[ModelEntry]:
    exclude = _CATEGORY_EXCLUDE_PATTERNS.get(category)
    out = []
    for m in _load():
        if m.category != category:
            continue
        if shapes is not None and m.shape not in shapes:
            continue
        if exclude and exclude.search(m.id):
            continue
        out.append(m)
    return out


def list_ids(category: str, shapes: tuple[str, ...] | None = None) -> list[str]:
    return [m.id for m in filter_models(category, shapes)]


# --------------------------------------------------------------------------
# Display-string helpers (provider-prefixed dropdown labels).
#
# Format: `[<provider>] <display_name> — <endpoint_id>`
# Sorted by provider then display_name so type-ahead "kling" jumps straight to
# the Kling family. The endpoint_id is appended for disambiguation when two
# models share a display_name AND so the parser can recover the canonical id.
# --------------------------------------------------------------------------


_DISPLAY_SEP = " — "  # em dash with surrounding spaces; rare in real display names


def extract_provider(endpoint_id: str) -> str:
    """First path segment of an endpoint_id. Empty → empty."""
    if not endpoint_id:
        return ""
    return endpoint_id.split("/", 1)[0]


def build_display_string(entry: ModelEntry) -> str:
    provider = extract_provider(entry.id)
    return f"[{provider}] {entry.display_name}{_DISPLAY_SEP}{entry.id}"


def parse_display_string(value: str) -> str:
    """Recover the endpoint_id from a display string `[provider] Name — endpoint`.

    Strict: raises `ValueError` on anything that doesn't match the format.
    The model_id widget always serializes display strings, so callers should
    never see anything else.
    """
    if not value or not isinstance(value, str):
        raise ValueError(f"empty or non-string value: {value!r}")
    if not value.startswith("["):
        raise ValueError(f"not a display string (no '[provider]' prefix): {value!r}")
    # Split on the LAST separator so display names containing " — " survive.
    idx = value.rfind(_DISPLAY_SEP)
    if idx < 0:
        raise ValueError(f"not a display string (no ' — ' separator): {value!r}")
    return value[idx + len(_DISPLAY_SEP):]


def list_display_strings(
    category: str, shapes: tuple[str, ...] | None = None
) -> list[str]:
    """Sorted list of display strings for the model dropdown."""
    entries = filter_models(category, shapes)
    entries_sorted = sorted(
        entries,
        key=lambda e: (extract_provider(e.id).lower(), e.display_name.lower(), e.id),
    )
    return [build_display_string(e) for e in entries_sorted]


def resolve(value: str) -> ModelEntry | None:
    """Look up a model by its display string. Returns None if unknown.

    Raises `ValueError` on malformed input — callers handle this as a 400.
    """
    endpoint_id = parse_display_string(value)
    return get(endpoint_id)
