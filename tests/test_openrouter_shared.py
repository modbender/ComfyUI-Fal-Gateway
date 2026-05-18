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


def test_entry_for_builds_chat_completion_entry_with_override():
    """xAI / Meta / Mistral hit the override; the display label should
    use the override value not the Title-cased fallback."""
    model = {
        "id": "x-ai/grok-4.3",
        "name": "Grok 4.3",
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
        "name": "Gemini 2.5 Pro",
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
    """If the disk cache returns a non-None list, load_models returns it
    without calling the live fetch."""
    cached = [{"id": "vendor/a", "name": "A"}]
    with patch.object(shared.openrouter_cache, "load_if_fresh", return_value=cached) as load_mock, \
         patch.object(shared.openrouter_catalog, "fetch_all_models") as fetch_mock:
        result = load_models()
    assert result == cached
    load_mock.assert_called_once()
    fetch_mock.assert_not_called()


def test_load_models_falls_through_to_live_fetch_and_writes_back():
    """Cache miss → live fetch → write result back to disk."""
    fresh = [{"id": "vendor/b", "name": "B"}]
    with patch.object(shared.openrouter_cache, "load_if_fresh", return_value=None), \
         patch.object(shared.openrouter_catalog, "fetch_all_models", return_value=fresh), \
         patch.object(shared.openrouter_cache, "write") as write_mock:
        result = load_models()
    assert result == fresh
    write_mock.assert_called_once_with(fresh)


def test_load_models_does_not_write_back_empty_fetch_result():
    """If the live fetch fails (returns []), don't poison the cache with
    an empty list — leave any older cached file in place so the next
    successful fetch (or a manual refresh) can repopulate it."""
    with patch.object(shared.openrouter_cache, "load_if_fresh", return_value=None), \
         patch.object(shared.openrouter_catalog, "fetch_all_models", return_value=[]), \
         patch.object(shared.openrouter_cache, "write") as write_mock:
        result = load_models()
    assert result == []
    write_mock.assert_not_called()
