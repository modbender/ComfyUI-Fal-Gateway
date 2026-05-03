"""Model registry — in-memory list of fal.ai models with display + filter helpers.

Loading order on first access (delegated to `storage.catalog_cache`):
  1. `cache/catalog.json` if present, fresh, and schema-current.
  2. Live fetch via `fal.catalog.fetch_active_video_models()` (blocks once,
     then persisted to cache for subsequent restarts).
  3. `src/data/fallback_catalog.json` (bundled, offline-bootable last resort).

Curated entries from the bundled fallback override live entries of the same
endpoint id — better-than-default widget specs for common models (Seedance,
Kling, MiniMax). For live entries without curated specs, `schema_resolver`
parses each model's OpenAPI 3.0 schema; on parse failure we synthesise a
minimal spec from the model's category.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from .endpoint_overrides import apply_widget_overrides
from .fal import catalog as fal_catalog
from .schema_resolver import SchemaError, parse_openapi
from .storage import catalog_cache
from .widget_spec import ModelEntry, WidgetSpec


_log = logging.getLogger("fal_gateway.registry")

_lock = threading.Lock()
_models: list[ModelEntry] | None = None


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


def _entry_from_raw(raw: dict[str, Any]) -> ModelEntry | None:
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

    widgets = apply_widget_overrides(str(endpoint_id), widgets)

    return ModelEntry(
        id=str(endpoint_id),
        display_name=str(display),
        category=str(category),
        shape=shape,
        description=str(description),
        widgets=widgets,
    )


def _live_fetch() -> list[ModelEntry] | None:
    try:
        per_category = fal_catalog.fetch_active_video_models()
    except Exception as exc:  # noqa: BLE001 — fall through to fallback
        _log.warning("live catalog fetch failed: %s", exc)
        return None

    out: list[ModelEntry] = []
    for category, raw_list in per_category.items():
        for raw in raw_list:
            entry = _entry_from_raw(raw)
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
    fallback = catalog_cache.load_fallback()

    cached = catalog_cache.load_if_fresh()
    if cached is not None:
        return _merge(fallback, cached)

    live = _live_fetch()
    if live is not None:
        merged = _merge(fallback, live)
        catalog_cache.write(merged)
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
# that includes embeddings + moderation + tool endpoints alongside chat models.
# Each value is a LIST of regex patterns — a model is excluded if ANY matches.
# Adding a new exclusion = one entry in the right list.
_CATEGORY_EXCLUDE_PATTERNS: dict[str, list["_re.Pattern[str]"]] = {
    "llm": [
        # Embedding endpoints aren't chat — keep T2T focused on generation.
        _re.compile(r"/embeddings?$", _re.IGNORECASE),
        # OpenRouter's bare router endpoint (no `/openai/v1/...` path) is a
        # parent that doesn't expose a usable inference contract on its own.
        _re.compile(r"^openrouter/router$"),
        # Moderation / guard models classify content; not chat-model-shaped.
        _re.compile(r"-guard\b", _re.IGNORECASE),
        # Single-purpose tools, not general-purpose chat.
        _re.compile(r"video-prompt-generator", _re.IGNORECASE),
    ],
}


def filter_models(category: str, shapes: tuple[str, ...] | None = None) -> list[ModelEntry]:
    excludes = _CATEGORY_EXCLUDE_PATTERNS.get(category, [])
    out = []
    for m in _load():
        if m.category != category:
            continue
        if shapes is not None and m.shape not in shapes:
            continue
        if any(p.search(m.id) for p in excludes):
            continue
        out.append(m)
    return out


def list_ids(category: str, shapes: tuple[str, ...] | None = None) -> list[str]:
    return [m.id for m in filter_models(category, shapes)]


# --------------------------------------------------------------------------
# Display-string helpers (provider-prefixed dropdown labels).
#
# Format:
#   `[<provider>] <display_name>`                    — when unique
#   `[<provider>] <display_name> (<endpoint_id>)`    — when display_name
#                                                       collides within provider
#
# Sorted by provider then display_name so type-ahead "kling" jumps to the
# Kling family. Endpoint_id is shown only as a disambiguator (rarely needed)
# instead of always appended — keeps labels readable.
#
# Backward-compat: `resolve()` accepts the LEGACY long format
#   `[<provider>] <display_name> — <endpoint_id>`
# so saved workflows from earlier versions keep working.
# --------------------------------------------------------------------------


_LEGACY_DISPLAY_SEP = " — "  # em-dash separator used by the legacy long format


def extract_provider(endpoint_id: str) -> str:
    """First path segment of an endpoint_id. Empty → empty."""
    if not endpoint_id:
        return ""
    return endpoint_id.split("/", 1)[0]


def _build_display_map(entries: list[ModelEntry]) -> dict[str, str]:
    """Compute `{endpoint_id: display_string}` for a list of entries.

    Display strings use the short form unless display_name collides within
    a provider — in which case the endpoint_id is appended in parens.
    """
    from collections import defaultdict

    bucket: dict[tuple[str, str], list[ModelEntry]] = defaultdict(list)
    for e in entries:
        bucket[(extract_provider(e.id), e.display_name)].append(e)

    out: dict[str, str] = {}
    for (provider, name), members in bucket.items():
        if len(members) == 1:
            out[members[0].id] = f"[{provider}] {name}"
        else:
            for m in members:
                out[m.id] = f"[{provider}] {name} ({m.id})"
    return out


def build_display_string(entry: ModelEntry) -> str:
    """Single-entry helper. For lists, prefer `_build_display_map` which
    can detect collisions across siblings."""
    provider = extract_provider(entry.id)
    return f"[{provider}] {entry.display_name}"


def list_display_strings(
    category: str, shapes: tuple[str, ...] | None = None
) -> list[str]:
    """Sorted list of display strings for the model dropdown."""
    entries = filter_models(category, shapes)
    entries_sorted = sorted(
        entries,
        key=lambda e: (extract_provider(e.id).lower(), e.display_name.lower(), e.id),
    )
    display_map = _build_display_map(entries_sorted)
    return [display_map[e.id] for e in entries_sorted]


def _parse_legacy_display_string(value: str) -> str | None:
    """Pull the endpoint_id out of `[provider] Name — endpoint_id` (legacy).

    Returns None if `value` doesn't match the legacy long form.
    """
    idx = value.rfind(_LEGACY_DISPLAY_SEP)
    if idx < 0:
        return None
    return value[idx + len(_LEGACY_DISPLAY_SEP):]


def resolve(value: str) -> ModelEntry | None:
    """Look up a model by its display string. Returns None if unknown.

    Recognises three cases:
      1. Current short form `[provider] DisplayName` → reverse-lookup via display_map
      2. Current collision form `[provider] DisplayName (endpoint_id)` → reverse-lookup
      3. LEGACY `[provider] DisplayName — endpoint_id` → trailing-id parse (back-compat)
    """
    if not value or not isinstance(value, str):
        raise ValueError(f"empty or non-string value: {value!r}")
    if not value.startswith("["):
        raise ValueError(f"not a display string (no '[provider]' prefix): {value!r}")

    # Build a reverse map across the entire registry. Cheap (~hundreds of entries).
    all_entries = _load()
    forward = _build_display_map(all_entries)
    reverse = {v: k for k, v in forward.items()}

    endpoint_id = reverse.get(value)
    if endpoint_id is not None:
        return get(endpoint_id)

    # Legacy long-format fallback for saved workflows from earlier versions.
    legacy_id = _parse_legacy_display_string(value)
    if legacy_id is not None:
        return get(legacy_id)

    raise ValueError(f"display string didn't resolve to a model: {value!r}")
