"""Disk-backed cache for OpenRouter's vision-capable model list.

Mirrors `storage/catalog.py`'s shape: schema-version-aware load, TTL freshness
check, atomic write. The cached payload is a list of plain dicts (not
ModelEntry) — these models live as CatalogEntry rows in catalogs/i2t.py, not
as registry entries.

Cold start with no cache + offline: returns empty list. The I2T dropdown
falls back to fal-direct vision models only.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger("fal_gateway.storage.openrouter")

_PKG_ROOT = Path(__file__).resolve().parent.parent  # src/
CACHE_PATH = _PKG_ROOT.parent / "cache" / "openrouter.json"

CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days, matches fal catalog TTL
SCHEMA_VERSION = 1


def load_if_fresh() -> list[dict] | None:
    """Read the cache if present, fresh, and schema-current. None otherwise."""
    if not CACHE_PATH.exists():
        return None
    try:
        age = time.time() - CACHE_PATH.stat().st_mtime
        if age > CACHE_TTL_SECONDS:
            _log.info("openrouter cache stale (%.1f days); refetching", age / 86400)
            return None
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _log.warning("openrouter cache read failed: %s", exc)
        return None
    if data.get("schema_version") != SCHEMA_VERSION:
        _log.info("openrouter cache schema mismatch; refetching")
        return None
    models = data.get("models")
    if not isinstance(models, list):
        return None
    return models


def write(models: list[dict]) -> None:
    """Atomic write."""
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "models": models,
        }
        tmp = CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(CACHE_PATH)
        _log.info("wrote %d openrouter models to %s", len(models), CACHE_PATH)
    except OSError as exc:
        _log.warning("openrouter cache write failed: %s", exc)


def clear() -> bool:
    if not CACHE_PATH.exists():
        return False
    CACHE_PATH.unlink()
    return True
