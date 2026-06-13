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
  5 → 6: added input_modalities field on ModelEntry
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from ..models import CatalogCacheFile
from ..widget_spec import ModelEntry


_log = logging.getLogger("fal_gateway.storage.catalog")

_PKG_ROOT = Path(__file__).resolve().parent.parent  # src/
FALLBACK_PATH = _PKG_ROOT / "data" / "fallback_catalog.json"
CACHE_PATH = _PKG_ROOT.parent / "cache" / "catalog.json"

CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days
SCHEMA_VERSION = 6


def load_fallback() -> list[ModelEntry]:
    """Read the bundled fallback catalog from `src/data/fallback_catalog.json`."""
    with open(FALLBACK_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return [ModelEntry.from_dict(m) for m in data.get("models", [])]


def load_any() -> tuple[list[ModelEntry] | None, bool]:
    """Read the cache regardless of TTL. Returns `(models, is_stale)`.

    `models` is None when the cache is missing, unreadable, or on a wrong
    schema (those force a real refetch). `is_stale` is True when the file
    is older than `CACHE_TTL_SECONDS` — callers use it to decide whether
    to kick off a background refresh.
    """
    if not CACHE_PATH.exists():
        return None, True
    try:
        age = time.time() - CACHE_PATH.stat().st_mtime
        cache = CatalogCacheFile.model_validate_json(
            CACHE_PATH.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError, ValueError) as exc:
        _log.warning("cache read failed: %s", exc)
        return None, True
    if cache.schema_version != SCHEMA_VERSION:
        _log.info(
            "cache schema_version %s != %s; refetching",
            cache.schema_version,
            SCHEMA_VERSION,
        )
        return None, True
    models = [ModelEntry.from_dict(raw) for raw in cache.models]
    is_stale = age > CACHE_TTL_SECONDS
    _log.info(
        "loaded %d models from cache (age %.1f hours, %s)",
        len(models),
        age / 3600,
        "stale" if is_stale else "fresh",
    )
    return models, is_stale


def load_if_fresh() -> list[ModelEntry] | None:
    """Read the cache only when present, fresh, and schema-current.

    Thin wrapper over `load_any()` for callers that want strict freshness.
    """
    models, is_stale = load_any()
    if models is None or is_stale:
        return None
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
        _atomic_write(cache.model_dump_json(indent=2))
        _log.info("wrote %d models to %s", len(models), CACHE_PATH)
    except OSError as exc:
        _log.warning("cache write failed: %s", exc)


def _atomic_write(text: str) -> None:
    """Write `text` to CACHE_PATH atomically via a unique temp file in the same
    directory + os.replace. A unique temp name means concurrent writers can't
    clobber each other's in-progress `.tmp` (same-filesystem rename stays atomic)."""
    fd, tmp = tempfile.mkstemp(
        dir=CACHE_PATH.parent, prefix=CACHE_PATH.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, CACHE_PATH)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def clear() -> bool:
    """Delete the cache file. Returns True if a file was deleted; False if
    no cache existed. Raises OSError if the file exists but can't be
    removed (caller decides how to surface)."""
    if not CACHE_PATH.exists():
        return False
    CACHE_PATH.unlink()
    return True
