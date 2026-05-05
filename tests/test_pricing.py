"""Tests for src/storage/pricing.py — the pricing-only cache file with skip-list
and 30-day TTL.

Background refresh is invoked via a real `threading.Thread` in production;
tests stub `fal.pricing.fetch_all_pricing` and run the refresh
synchronously in-thread to keep tests deterministic.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.storage import pricing as pricing_cache


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Redirect _CACHE_PATH to a tmp file and reset module state per test."""
    cache_file = tmp_path / "pricing.json"
    monkeypatch.setattr(pricing_cache, "_CACHE_PATH", cache_file)
    pricing_cache._reset_for_testing()
    yield
    pricing_cache._reset_for_testing()


def _write_cache(tmp_path, **overrides):
    """Helper to seed an on-disk pricing cache file."""
    payload = {
        "schema_version": pricing_cache.SCHEMA_VERSION,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "prices": {
            "fal-ai/flux/dev": {"unit_price": 0.025, "unit": "image", "currency": "USD"}
        },
        "no_pricing": ["fal-ai/some/internal-tool"],
    }
    payload.update(overrides)
    cache = pricing_cache._CACHE_PATH
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(payload), encoding="utf-8")


# ---- load / freshness --------------------------------------------------


def test_get_returns_none_when_cache_missing():
    assert pricing_cache.get("fal-ai/flux/dev") is None


def test_get_returns_payload_after_load_from_disk(tmp_path):
    _write_cache(tmp_path)
    assert pricing_cache.get("fal-ai/flux/dev") == {
        "unit_price": 0.025,
        "unit": "image",
        "currency": "USD",
    }


def test_get_for_response_returns_consistent_shape_for_unknown():
    """Schema route must always get the three keys, even when unknown."""
    out = pricing_cache.get_for_response("fal-ai/unknown")
    assert out == {"unit_price": None, "unit": None, "currency": None}


def test_get_for_response_returns_pricing_when_known(tmp_path):
    _write_cache(tmp_path)
    assert pricing_cache.get_for_response("fal-ai/flux/dev") == {
        "unit_price": 0.025,
        "unit": "image",
        "currency": "USD",
    }


def test_is_stale_true_when_no_cache():
    assert pricing_cache.is_stale() is True


def test_is_stale_false_for_fresh_cache(tmp_path):
    _write_cache(tmp_path)
    assert pricing_cache.is_stale() is False


def test_is_stale_true_when_older_than_ttl(tmp_path):
    old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    _write_cache(tmp_path, fetched_at=old)
    assert pricing_cache.is_stale() is True


def test_load_ignores_wrong_schema_version(tmp_path):
    _write_cache(tmp_path, schema_version=99)
    # Wrong schema version → treated as missing.
    assert pricing_cache.get("fal-ai/flux/dev") is None
    assert pricing_cache.is_stale() is True


# ---- refresh trigger ---------------------------------------------------


def test_trigger_refresh_starts_thread_when_stale():
    """When cache is stale, trigger_refresh_if_stale spawns the worker."""
    captured_ids: list[list[str]] = []

    def fake_fetch(endpoint_ids, timeout_s=20.0, skip_ids=None):
        captured_ids.append(list(endpoint_ids))
        return ({"fal-ai/x": {"unit_price": 0.1, "unit": "image", "currency": "USD"}}, set())

    with patch.object(pricing_cache.fal_pricing, "fetch_all_pricing", fake_fetch):
        started = pricing_cache.trigger_refresh_if_stale(["fal-ai/x", "fal-ai/y"])
        assert started is True
        # Wait for the daemon thread to finish.
        for t in [t for t in __import__("threading").enumerate() if t.name == "fal-gateway-pricing-refresh"]:
            t.join(timeout=2.0)

    assert captured_ids == [["fal-ai/x", "fal-ai/y"]]
    assert pricing_cache.get("fal-ai/x") == {"unit_price": 0.1, "unit": "image", "currency": "USD"}


def test_trigger_refresh_noop_when_fresh(tmp_path):
    _write_cache(tmp_path)
    started = pricing_cache.trigger_refresh_if_stale(["fal-ai/x"])
    assert started is False


def test_trigger_refresh_noop_when_already_in_progress():
    """Two back-to-back trigger calls only start one thread."""
    import threading
    barrier = threading.Event()

    def slow_fetch(endpoint_ids, timeout_s=20.0, skip_ids=None):
        barrier.wait(timeout=2.0)  # block until the test releases us
        return ({}, set())

    with patch.object(pricing_cache.fal_pricing, "fetch_all_pricing", slow_fetch):
        first = pricing_cache.trigger_refresh_if_stale(["fal-ai/x"])
        second = pricing_cache.trigger_refresh_if_stale(["fal-ai/x"])
        barrier.set()
        for t in [t for t in threading.enumerate() if t.name == "fal-gateway-pricing-refresh"]:
            t.join(timeout=2.0)
    assert first is True
    assert second is False  # the second call short-circuited


# ---- skip-list semantics -----------------------------------------------


def test_refresh_persists_no_pricing_set():
    """The newly_no_pricing set returned by fetch_all_pricing must be persisted."""
    def fake_fetch(endpoint_ids, timeout_s=20.0, skip_ids=None):
        return ({}, {"fal-ai/unknown-1", "fal-ai/unknown-2"})

    with patch.object(pricing_cache.fal_pricing, "fetch_all_pricing", fake_fetch):
        pricing_cache.trigger_refresh_if_stale(["fal-ai/unknown-1", "fal-ai/unknown-2"])
        for t in [t for t in __import__("threading").enumerate() if t.name == "fal-gateway-pricing-refresh"]:
            t.join(timeout=2.0)

    # Reload from disk to confirm persistence.
    pricing_cache._reset_for_testing()
    on_disk = json.loads(pricing_cache._CACHE_PATH.read_text())
    assert sorted(on_disk["no_pricing"]) == ["fal-ai/unknown-1", "fal-ai/unknown-2"]


def test_subsequent_refresh_passes_no_pricing_as_skip_ids(tmp_path):
    """Once an id is on the no_pricing list, the next refresh must skip it."""
    _write_cache(tmp_path)
    received_skip: list[set[str]] = []

    def fake_fetch(endpoint_ids, timeout_s=20.0, skip_ids=None):
        received_skip.append(skip_ids or set())
        return ({}, set())

    # The cache is fresh after _write_cache; force-stale by clearing fetched_at.
    pricing_cache._reset_for_testing()
    _write_cache(
        tmp_path,
        fetched_at=(datetime.now(timezone.utc) - timedelta(days=31)).isoformat(),
    )

    with patch.object(pricing_cache.fal_pricing, "fetch_all_pricing", fake_fetch):
        pricing_cache.trigger_refresh_if_stale(["fal-ai/flux/dev", "fal-ai/some/internal-tool"])
        for t in [t for t in __import__("threading").enumerate() if t.name == "fal-gateway-pricing-refresh"]:
            t.join(timeout=2.0)

    assert received_skip == [{"fal-ai/some/internal-tool"}]


# ---- clear() -----------------------------------------------------------


def test_clear_removes_disk_file_and_resets_state(tmp_path):
    _write_cache(tmp_path)
    assert pricing_cache.get("fal-ai/flux/dev") is not None
    pricing_cache.clear()
    assert pricing_cache.get("fal-ai/flux/dev") is None
    assert not pricing_cache._CACHE_PATH.exists()
    assert pricing_cache.is_stale() is True
