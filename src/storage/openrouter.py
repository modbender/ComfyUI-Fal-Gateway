"""Disk-backed cache for OpenRouter's FULL model list.

Mirrors `storage/catalog.py`'s shape: schema-version-aware load, TTL freshness
check, atomic write. The cached payload is the unfiltered list of model dicts
(`{id, name, input_modalities, output_modalities, description}`) parsed from
`/api/v1/models`. Callers in `catalogs/t2t.py` and `catalogs/i2t.py` apply
their own modality filters on read — keeping the cache shared means a single
HTTP fetch serves both nodes.

Schema v1 was vision-only; v2 stores the full list with output_modalities.
Bumping the version forces a one-time refetch when an older cache is loaded.

Cold start with no cache + offline: returns empty list. Both T2T and I2T
dropdowns fall back to fal-direct entries only.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger("fal_gateway.storage.openrouter")

_PKG_ROOT = Path(__file__).resolve().parent.parent  # src/
CACHE_PATH = _PKG_ROOT.parent / "cache" / "openrouter.json"

CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days, matches fal catalog TTL
SCHEMA_VERSION = 2  # bumped from 1 (vision-only) to 2 (full model list w/ output_modalities)


def load_any() -> tuple[list[dict] | None, bool]:
    """Read the cache regardless of TTL. Returns `(models, is_stale)`.

    `models` is None when missing, unreadable, or schema-wrong (those force
    a real refetch). `is_stale` is True when the file is older than
    `CACHE_TTL_SECONDS` — callers use it to decide whether to background-refresh.
    """
    if not CACHE_PATH.exists():
        return None, True
    try:
        age = time.time() - CACHE_PATH.stat().st_mtime
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _log.warning("openrouter cache read failed: %s", exc)
        return None, True
    if data.get("schema_version") != SCHEMA_VERSION:
        _log.info("openrouter cache schema mismatch; refetching")
        return None, True
    models = data.get("models")
    if not isinstance(models, list):
        return None, True
    return models, age > CACHE_TTL_SECONDS


def load_if_fresh() -> list[dict] | None:
    """Read the cache only when present, fresh, and schema-current."""
    models, is_stale = load_any()
    if models is None or is_stale:
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
        _atomic_write(json.dumps(payload, indent=2))
        _log.info("wrote %d openrouter models to %s", len(models), CACHE_PATH)
    except OSError as exc:
        _log.warning("openrouter cache write failed: %s", exc)


def _atomic_write(text: str) -> None:
    """Write `text` to CACHE_PATH atomically via a unique temp file in the same
    directory + os.replace, so concurrent writers can't clobber each other's
    in-progress `.tmp` (same-filesystem rename stays atomic)."""
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
    if not CACHE_PATH.exists():
        return False
    CACHE_PATH.unlink()
    return True
