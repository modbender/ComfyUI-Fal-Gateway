import json

from src.storage import catalog as cache


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
