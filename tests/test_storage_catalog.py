import json

from src.storage import catalog as cache
from src.widget_spec import ModelEntry


def _entry() -> ModelEntry:
    return ModelEntry(
        id="fal-ai/flux/dev",
        display_name="Flux Dev",
        category="text-to-image",
        shape="text_only",
    )


def test_load_if_fresh_returns_none_for_old_schema_version(tmp_path, monkeypatch):
    fake_cache = tmp_path / "catalog.json"
    fake_cache.write_text(json.dumps({
        "schema_version": 5,  # old version
        "fetched_at": "2026-05-01T00:00:00+00:00",
        "models": [],
    }))
    monkeypatch.setattr(cache, "CACHE_PATH", fake_cache)
    assert cache.load_if_fresh() is None


def test_schema_version_is_current():
    assert cache.SCHEMA_VERSION == 6


def test_write_uses_unique_tmp_not_shared_suffix(tmp_path, monkeypatch):
    """Concurrent writers must not share a fixed `.tmp` path. The temp file
    the write renames from must NOT be the old fixed `CACHE_PATH.with_suffix('.tmp')`."""
    import os

    cache_file = tmp_path / "catalog.json"
    monkeypatch.setattr(cache, "CACHE_PATH", cache_file)
    fixed_tmp = cache_file.with_suffix(".tmp")

    captured: list[str] = []
    real_replace = os.replace

    def spy_replace(src, dst, *a, **k):
        captured.append(str(src))
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(cache.os, "replace", spy_replace)
    cache.write([_entry()])

    assert len(captured) == 1
    assert captured[0] != str(fixed_tmp)


def test_write_round_trips_and_leaves_no_tmp(tmp_path, monkeypatch):
    cache_file = tmp_path / "catalog.json"
    monkeypatch.setattr(cache, "CACHE_PATH", cache_file)

    cache.write([_entry()])
    cache.write([_entry()])  # second sequential write must also succeed

    loaded = cache.load_if_fresh()
    assert loaded is not None
    assert loaded[0].id == "fal-ai/flux/dev"
    leftover = list(tmp_path.glob("*.tmp"))
    assert leftover == []


def test_load_fallback_returns_empty_on_missing_file(tmp_path, monkeypatch):
    """A missing bundled catalog must not crash node loading — return []."""
    monkeypatch.setattr(cache, "FALLBACK_PATH", tmp_path / "does_not_exist.json")
    assert cache.load_fallback() == []


def test_load_fallback_returns_empty_on_malformed_json(tmp_path, monkeypatch):
    """A corrupt bundled catalog must not crash node loading — return []."""
    bad = tmp_path / "fallback_catalog.json"
    bad.write_text("{ this is not valid json ]")
    monkeypatch.setattr(cache, "FALLBACK_PATH", bad)
    assert cache.load_fallback() == []
