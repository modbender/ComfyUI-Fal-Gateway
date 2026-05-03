"""Disk-backed catalog cache (`cache/catalog.json`).

Owns the file I/O for the model catalog: schema-version-aware load,
TTL freshness check, atomic write, and the bundled fallback catalog
shipped under `src/data/fallback_catalog.json` for offline-bootable
first-runs.

Bumps to `SCHEMA_VERSION` invalidate existing caches and force a refetch
on the next ComfyUI restart. Last bumps:
  1 → 2: added text-to-image + image-to-image categories
  2 → 3: added llm + vision categories (v0.3.0)
  3 → 4: added pricing fields (unit_price/unit/currency on ModelEntry)
  4 → 5: extracted pricing into separate cache/pricing.json
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from ..api_models import CatalogCacheFile
from ..endpoint_overrides import apply_widget_overrides
from ..widget_spec import ModelEntry


_log = logging.getLogger("fal_gateway.storage.catalog")

_PKG_ROOT = Path(__file__).resolve().parent.parent  # src/
FALLBACK_PATH = _PKG_ROOT / "data" / "fallback_catalog.json"
CACHE_PATH = _PKG_ROOT.parent / "cache" / "catalog.json"

CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days
SCHEMA_VERSION = 5


def load_fallback() -> list[ModelEntry]:
    """Read the bundled fallback catalog from `src/data/fallback_catalog.json`."""
    with open(FALLBACK_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return [ModelEntry.from_dict(m) for m in data.get("models", [])]


def load_if_fresh() -> list[ModelEntry] | None:
    """Read `cache/catalog.json` if present, fresh, and schema-current.

    Returns None when the cache is missing, stale, or unreadable — caller
    should fall through to a live fetch.

    Re-applies `apply_widget_overrides` on every load so future override
    registry changes take effect without forcing a cache refetch.
    """
    if not CACHE_PATH.exists():
        return None
    try:
        age = time.time() - CACHE_PATH.stat().st_mtime
        if age > CACHE_TTL_SECONDS:
            _log.info("cached catalog is stale (%.1f days old); refetching", age / 86400)
            return None
        cache = CatalogCacheFile.model_validate_json(
            CACHE_PATH.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError, ValueError) as exc:
        _log.warning("cache read failed: %s", exc)
        return None
    if cache.schema_version != SCHEMA_VERSION:
        _log.info(
            "cache schema_version %s != %s; refetching",
            cache.schema_version,
            SCHEMA_VERSION,
        )
        return None
    models: list[ModelEntry] = []
    for raw in cache.models:
        entry = ModelEntry.from_dict(raw)
        entry.widgets = apply_widget_overrides(entry.id, entry.widgets)
        models.append(entry)
    _log.info("loaded %d models from cache (age %.1f hours)", len(models), age / 3600)
    return models


def write(models: list[ModelEntry]) -> None:
    """Atomic write to `cache/catalog.json` (temp file + rename)."""
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        cache = CatalogCacheFile(
            schema_version=SCHEMA_VERSION,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            models=[m.to_dict() for m in models],
        )
        tmp = CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(cache.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(CACHE_PATH)
        _log.info("wrote %d models to %s", len(models), CACHE_PATH)
    except OSError as exc:
        _log.warning("cache write failed: %s", exc)


def clear() -> bool:
    """Delete the cache file. Returns True if a file was deleted; False if
    no cache existed. Raises OSError if the file exists but can't be
    removed (caller decides how to surface)."""
    if not CACHE_PATH.exists():
        return False
    CACHE_PATH.unlink()
    return True
