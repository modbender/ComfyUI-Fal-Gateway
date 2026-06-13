"""Tests for `src/catalogs/_openrouter_shared.py` — the loader +
CatalogEntry builder shared by t2t.py and i2t.py."""

from __future__ import annotations

from unittest.mock import patch

from src.catalogs import _openrouter_shared as shared
from src.catalogs._openrouter_shared import (
    PROVIDER_DISPLAY_OVERRIDES,
    entry_for,
    load_models,
    provider_from_id,
)


def test_provider_from_id_splits_on_first_slash():
    assert provider_from_id("anthropic/claude-sonnet-4.5") == "anthropic"
    assert provider_from_id("meta-llama/llama-3.3-70b-instruct") == "meta-llama"


def test_provider_from_id_returns_unknown_for_unprefixed():
    """Defensive: OpenRouter IDs always have a vendor prefix, but if one
    ever appears without a slash, fall back to 'unknown' instead of
    crashing the catalog build."""
    assert provider_from_id("oddball-no-slash") == "unknown"


def test_provider_display_overrides_table_contents():
    """Pin the alias map. These are the providers whose Title-cased
    hyphenated IDs gave ugly labels — the override produces a clean one.
    Any change here will be reflected in the user's dropdown."""
    assert PROVIDER_DISPLAY_OVERRIDES["x-ai"] == "xAI"
    assert PROVIDER_DISPLAY_OVERRIDES["meta-llama"] == "Meta"
    assert PROVIDER_DISPLAY_OVERRIDES["mistralai"] == "Mistral"
    assert PROVIDER_DISPLAY_OVERRIDES["openai"] == "OpenAI"
    assert PROVIDER_DISPLAY_OVERRIDES["deepseek"] == "DeepSeek"


def test_entry_for_strips_provider_prefix_from_openrouter_name():
    """OpenRouter names follow 'Provider: Model Name' — the provider prefix is
    redundant with the bracketed label we add, so it must be stripped."""
    model = {
        "id": "google/gemini-3.1-flash-lite",
        "name": "Google: Gemini 3.1 Flash Lite",
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "description": "",
    }
    entry = entry_for(model, "openrouter/router/vision")
    assert entry.display_name == "[Google] Gemini 3.1 Flash Lite"


def test_entry_for_builds_chat_completion_entry_with_override():
    """xAI / Meta / Mistral hit the override; the display label should
    use the override value not the Title-cased fallback."""
    model = {
        "id": "x-ai/grok-4.3",
        "name": "xAI: Grok 4.3",
        "input_modalities": ["text"],
        "output_modalities": ["text"],
        "description": "",
    }
    entry = entry_for(model, "openrouter/router/openai/v1/chat/completions")
    assert entry.display_name == "[xAI] Grok 4.3"
    assert entry.endpoint_id == "openrouter/router/openai/v1/chat/completions"
    assert entry.extra_payload == {"model": "x-ai/grok-4.3"}
    assert entry.provider == "x-ai"


def test_entry_for_falls_back_to_title_cased_provider():
    """Provider not in PROVIDER_DISPLAY_OVERRIDES: title-case the
    hyphenated id. `google` → `Google`, `nvidia` → `Nvidia`, etc."""
    model = {
        "id": "google/gemini-2.5-pro",
        "name": "Google: Gemini 2.5 Pro",
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "description": "",
    }
    entry = entry_for(model, "openrouter/router/vision")
    assert entry.display_name == "[Google] Gemini 2.5 Pro"
    assert entry.endpoint_id == "openrouter/router/vision"
    assert entry.extra_payload == {"model": "google/gemini-2.5-pro"}


def test_entry_for_falls_back_to_model_id_when_name_missing():
    """OpenRouter usually returns a `name`, but if it's absent fall back
    to the raw ID — avoids `None`-displaying entries in the dropdown."""
    model = {
        "id": "anthropic/claude-opus-4.7",
        "name": "",
        "input_modalities": ["text"],
        "output_modalities": ["text"],
        "description": "",
    }
    entry = entry_for(model, "openrouter/router/openai/v1/chat/completions")
    assert entry.display_name == "[Anthropic] anthropic/claude-opus-4.7"


def test_load_models_uses_cache_when_fresh():
    """If the disk cache returns a non-None fresh list, load_models returns
    it without calling the live fetch or queuing a background refresh."""
    cached = [{"id": "vendor/a", "name": "A"}]
    with patch.object(shared.openrouter_cache, "load_any", return_value=(cached, False)) as load_mock, \
         patch.object(shared.openrouter_catalog, "fetch_all_models") as fetch_mock, \
         patch.object(shared._background, "kick_off") as kick_mock:
        result = load_models()
    assert result == cached
    load_mock.assert_called_once()
    fetch_mock.assert_not_called()
    kick_mock.assert_not_called()


def test_load_models_returns_stale_and_kicks_off_background_refresh():
    """Stale-while-revalidate: stale cache is returned immediately AND a
    background refresh is queued so the next start sees fresh data."""
    cached = [{"id": "vendor/a", "name": "A"}]
    with patch.object(shared.openrouter_cache, "load_any", return_value=(cached, True)), \
         patch.object(shared.openrouter_catalog, "fetch_all_models") as fetch_mock, \
         patch.object(shared._background, "kick_off") as kick_mock:
        result = load_models()
    assert result == cached  # served immediately, no blocking fetch
    fetch_mock.assert_not_called()  # background thread does the fetch, not us
    kick_mock.assert_called_once()
    assert kick_mock.call_args.args[0] == "openrouter-refresh"


def test_load_models_cold_cache_returns_empty_and_kicks_off_background_refresh():
    """Cold cache must never block ComfyUI startup on a network fetch.
    load_models returns [] immediately, does NOT fetch synchronously, and
    schedules a background refresh so the next start sees fresh data."""
    with patch.object(shared.openrouter_cache, "load_any", return_value=(None, True)), \
         patch.object(shared.openrouter_catalog, "fetch_all_models") as fetch_mock, \
         patch.object(shared._background, "kick_off") as kick_mock:
        result = load_models()
    assert result == []
    fetch_mock.assert_not_called()  # no synchronous network fetch on the import thread
    kick_mock.assert_called_once()
    assert kick_mock.call_args.args[0] == "openrouter-refresh"


def test_load_models_cold_cache_does_not_write_synchronously():
    """Cold cache never writes to disk on the calling thread — the
    background refresh owns the fetch+write."""
    with patch.object(shared.openrouter_cache, "load_any", return_value=(None, True)), \
         patch.object(shared.openrouter_catalog, "fetch_all_models") as fetch_mock, \
         patch.object(shared.openrouter_cache, "write") as write_mock, \
         patch.object(shared._background, "kick_off"):
        result = load_models()
    assert result == []
    fetch_mock.assert_not_called()
    write_mock.assert_not_called()


def test_load_models_sanitizes_malformed_cached_entries():
    """A partially corrupt cache (non-dict entries, missing/non-string id)
    must not crash catalog construction — malformed entries are dropped."""
    cached = [{"id": "a/b", "name": "x"}, "garbage", {"no_id": 1}, {"id": 123}]
    with patch.object(shared.openrouter_cache, "load_any", return_value=(cached, False)), \
         patch.object(shared.openrouter_catalog, "fetch_all_models") as fetch_mock, \
         patch.object(shared._background, "kick_off"):
        result = load_models()
    assert result == [{"id": "a/b", "name": "x"}]
    fetch_mock.assert_not_called()
