import json
import os
import time

from src.storage import openrouter as cache


def test_load_if_fresh_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_PATH", tmp_path / "openrouter.json")
    assert cache.load_if_fresh() is None


def test_write_then_load_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_PATH", tmp_path / "openrouter.json")
    models = [
        {"id": "anthropic/claude-sonnet-4.5", "name": "Claude Sonnet 4.5",
         "input_modalities": ["text", "image"], "description": ""},
    ]
    cache.write(models)
    loaded = cache.load_if_fresh()
    assert loaded == models


def test_load_if_fresh_rejects_stale_cache(tmp_path, monkeypatch):
    cache_file = tmp_path / "openrouter.json"
    cache_file.write_text(json.dumps({
        "schema_version": cache.SCHEMA_VERSION,
        "fetched_at": "2026-01-01T00:00:00+00:00",
        "models": [],
    }))
    # Force mtime past TTL
    old = time.time() - cache.CACHE_TTL_SECONDS - 60
    os.utime(cache_file, (old, old))
    monkeypatch.setattr(cache, "CACHE_PATH", cache_file)
    assert cache.load_if_fresh() is None


def test_load_if_fresh_rejects_old_schema_version(tmp_path, monkeypatch):
    cache_file = tmp_path / "openrouter.json"
    cache_file.write_text(json.dumps({
        "schema_version": cache.SCHEMA_VERSION - 1,
        "fetched_at": "2026-05-01T00:00:00+00:00",
        "models": [],
    }))
    monkeypatch.setattr(cache, "CACHE_PATH", cache_file)
    assert cache.load_if_fresh() is None
