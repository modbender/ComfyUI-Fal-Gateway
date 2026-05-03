"""Pricing cache — separated from the main catalog cache.

Pricing data lives in `cache/pricing.json` with its own TTL (30 days). The
catalog (`cache/catalog.json`) refreshes weekly and no longer carries
pricing fields on `ModelEntry`. This decoupling means:

  - ComfyUI startup is fast: catalog loads from cache, no pricing fetch.
  - Pricing fetches happen lazily when the schema route first needs them,
    and then in a background thread so the user doesn't see a startup
    delay.
  - A persisted skip-list (`no_pricing`) tracks endpoint_ids that fal's
    pricing index doesn't recognise, so subsequent sweeps don't re-request
    them and re-bisect through the same 404s.

Module-level state is accessed through a `threading.Lock`. Reads use a
snapshot variable so the schema route never blocks on a refresh.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..api_models import PricingCacheFile
from ..fal import pricing as fal_pricing


_log = logging.getLogger("fal_gateway.pricing_cache")

# `__file__` is src/storage/pricing_cache.py — package root is src/, repo root
# is one level above. Cache files live at repo root, not inside src/.
_PKG_ROOT = Path(__file__).resolve().parent.parent  # src/
_CACHE_PATH = _PKG_ROOT.parent / "cache" / "pricing.json"

CACHE_TTL_SECONDS = 30 * 24 * 3600  # 30 days
SCHEMA_VERSION = 1


# Module-level cache state. Reads are snapshot-based (assignment is atomic in
# CPython); writes go through `_lock` to prevent torn updates during refresh.
_lock = threading.Lock()
_loaded: bool = False
_prices: dict[str, dict[str, Any]] = {}
_no_pricing: set[str] = set()
_fetched_at: datetime | None = None
_refresh_in_progress: bool = False


def _load_from_disk() -> None:
    global _loaded, _prices, _no_pricing, _fetched_at
    if not _CACHE_PATH.exists():
        _loaded = True
        return
    try:
        cache = PricingCacheFile.model_validate_json(
            _CACHE_PATH.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError, ValueError) as exc:
        _log.warning("pricing cache read failed: %s", exc)
        _loaded = True
        return
    if cache.schema_version != SCHEMA_VERSION:
        _log.info(
            "pricing cache schema_version %s != %s; will refetch",
            cache.schema_version,
            SCHEMA_VERSION,
        )
        _loaded = True
        return
    _prices = {k: v for k, v in cache.prices.items() if isinstance(v, dict)}
    _no_pricing = set(cache.no_pricing)
    try:
        _fetched_at = datetime.fromisoformat(cache.fetched_at)
    except ValueError:
        _fetched_at = None
    _loaded = True
    _log.info(
        "loaded pricing cache: %d prices, %d known no_pricing",
        len(_prices),
        len(_no_pricing),
    )


def _write_to_disk() -> None:
    """Atomic write — temp file + rename. Caller must hold `_lock`."""
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        cache = PricingCacheFile(
            schema_version=SCHEMA_VERSION,
            fetched_at=(_fetched_at or datetime.now(timezone.utc)).isoformat(),
            prices=_prices,
            no_pricing=sorted(_no_pricing),
        )
        tmp = _CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(cache.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(_CACHE_PATH)
        _log.info(
            "wrote pricing cache: %d prices, %d no_pricing",
            len(_prices),
            len(_no_pricing),
        )
    except OSError as exc:
        _log.warning("pricing cache write failed: %s", exc)


def _ensure_loaded() -> None:
    if not _loaded:
        with _lock:
            if not _loaded:  # double-check inside lock
                _load_from_disk()


def is_stale() -> bool:
    """True when the cache is missing, never-fetched, or older than TTL."""
    _ensure_loaded()
    if _fetched_at is None:
        return True
    age_s = (datetime.now(timezone.utc) - _fetched_at).total_seconds()
    return age_s > CACHE_TTL_SECONDS


def get(endpoint_id: str) -> dict[str, Any] | None:
    """Return the pricing payload for one endpoint, or None if unknown.

    "Unknown" includes both "we haven't fetched yet" and "fal returned no
    pricing for this id". The schema route uses `get_for_response()` for a
    consistent shape regardless.
    """
    _ensure_loaded()
    return _prices.get(endpoint_id)


def get_for_response(endpoint_id: str) -> dict[str, Any]:
    """Schema-route-friendly shape: always returns a dict with the three
    pricing keys, set to None when unknown."""
    info = get(endpoint_id) or {}
    return {
        "unit_price": info.get("unit_price"),
        "unit": info.get("unit"),
        "currency": info.get("currency"),
    }


def trigger_refresh_if_stale(endpoint_ids: list[str]) -> bool:
    """Kick off a background refresh if the cache is stale and no refresh
    is currently running. Idempotent — a second call during an in-flight
    refresh is a no-op.

    Returns True iff a refresh thread was started.
    """
    if not is_stale():
        return False
    return _start_refresh_thread(endpoint_ids)


def _start_refresh_thread(endpoint_ids: list[str]) -> bool:
    global _refresh_in_progress
    with _lock:
        if _refresh_in_progress:
            return False
        _refresh_in_progress = True
    thread = threading.Thread(
        target=_refresh_async,
        args=(list(endpoint_ids),),
        name="fal-gateway-pricing-refresh",
        daemon=True,
    )
    thread.start()
    return True


def _broadcast_updated() -> None:
    """Notify the frontend that pricing data is fresh so placed nodes can
    re-render their cost labels. No-op outside ComfyUI (tests, scripts)."""
    try:
        from server import PromptServer  # type: ignore[import-not-found]
    except ImportError:
        return
    try:
        PromptServer.instance.send_sync(
            "fal_gateway/pricing_updated", {"count": len(_prices)}
        )
    except Exception as exc:  # noqa: BLE001 — best-effort
        _log.debug("pricing_updated broadcast failed: %s", exc)


def _refresh_async(endpoint_ids: list[str]) -> None:
    """Run a pricing sweep in a worker thread and persist results.

    Held outside the lock during the network roundtrip; only state mutation
    + disk write happen under the lock so reads stay non-blocking.
    """
    global _prices, _no_pricing, _fetched_at, _refresh_in_progress
    succeeded = False
    try:
        skip = set(_no_pricing)  # snapshot — may be empty on first sweep
        prices, newly_no_pricing = fal_pricing.fetch_all_pricing(
            endpoint_ids, skip_ids=skip
        )
        with _lock:
            # Merge new prices over old (full refresh wins; partial sweep adds).
            _prices = {**_prices, **prices}
            _no_pricing = _no_pricing | newly_no_pricing
            _fetched_at = datetime.now(timezone.utc)
            _write_to_disk()
        _log.info(
            "pricing refresh complete: %d prices total, %d known no_pricing",
            len(prices),
            len(newly_no_pricing),
        )
        succeeded = True
    except Exception as exc:  # noqa: BLE001 — best-effort
        _log.warning("pricing refresh failed: %s", exc)
    finally:
        with _lock:
            _refresh_in_progress = False
    if succeeded:
        _broadcast_updated()


def clear() -> None:
    """Reset the in-memory cache and delete the on-disk file. Used by the
    user-triggered "refresh catalog cache" menu so the next schema lookup
    forces a fresh sweep."""
    global _loaded, _prices, _no_pricing, _fetched_at
    with _lock:
        _prices = {}
        _no_pricing = set()
        _fetched_at = None
        _loaded = True  # we just initialised an empty state
        if _CACHE_PATH.exists():
            try:
                _CACHE_PATH.unlink()
                _log.info("cleared pricing cache file %s", _CACHE_PATH)
            except OSError as exc:
                _log.warning("could not delete pricing cache: %s", exc)


# --- Test seam ----------------------------------------------------------


def _reset_for_testing() -> None:
    """Drop module-level state so tests can rebuild cleanly. Not for runtime use."""
    global _loaded, _prices, _no_pricing, _fetched_at, _refresh_in_progress
    with _lock:
        _loaded = False
        _prices = {}
        _no_pricing = set()
        _fetched_at = None
        _refresh_in_progress = False
