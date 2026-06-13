"""Tests for `model_registry._entry_from_raw` pricing plumbing + LLM exclude
patterns + endpoint-override application.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import src.model_registry as model_registry
from src.model_registry import _CATEGORY_EXCLUDE_PATTERNS, _entry_from_raw


_FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _raw(fixture_name: str) -> dict:
    with open(_FIXTURE_DIR / fixture_name, encoding="utf-8") as f:
        return json.load(f)


def _matches_any_llm_exclude(endpoint_id: str) -> bool:
    return any(p.search(endpoint_id) for p in _CATEGORY_EXCLUDE_PATTERNS["llm"])


def test_entry_from_raw_builds_basic_entry():
    raw = _raw("fal_ai_flux_dev.json")
    entry = _entry_from_raw(raw)
    assert entry is not None
    assert entry.id == "fal-ai/flux/dev"
    assert entry.category == "text-to-image"


def test_entry_from_raw_does_not_carry_pricing_fields():
    """Pricing lives in the separate pricing_cache (v0.4.x). ModelEntry must
    not have unit_price / unit / currency attributes anymore."""
    raw = _raw("fal_ai_flux_dev.json")
    entry = _entry_from_raw(raw)
    assert entry is not None
    assert not hasattr(entry, "unit_price")
    assert not hasattr(entry, "unit")
    assert not hasattr(entry, "currency")


# ---- LLM category exclude patterns -------------------------------------


def test_llm_excludes_embeddings():
    assert _matches_any_llm_exclude("openrouter/router/openai/v1/embeddings")
    assert _matches_any_llm_exclude("fal-ai/some-model/embedding")


def test_llm_excludes_bare_openrouter_router():
    """Bare `openrouter/router` parent isn't a usable inference endpoint."""
    assert _matches_any_llm_exclude("openrouter/router")


def test_llm_does_not_exclude_openrouter_chat_completions():
    assert not _matches_any_llm_exclude(
        "openrouter/router/openai/v1/chat/completions"
    )


def test_llm_excludes_guard_models():
    assert _matches_any_llm_exclude("fal-ai/qwen-3-guard")
    assert _matches_any_llm_exclude("fal-ai/llama-guard-2")


def test_llm_excludes_video_prompt_generator():
    assert _matches_any_llm_exclude("fal-ai/video-prompt-generator")


def test_llm_does_not_exclude_general_chat_models():
    assert not _matches_any_llm_exclude("nvidia/nemotron-3-nano-omni")
    assert not _matches_any_llm_exclude("fal-ai/bytedance/seed/v2/mini")


# Note: K1 moved widget-level model selection out of model_registry and
# into the curated T2T catalog (`src/catalogs/t2t.py`). The previous
# test for endpoint-level widget overrides in `_entry_from_raw` is gone.
# Catalog round-trip lives in `tests/test_catalogs.py`.


# ---- input_modalities derivation -----------------------------------------------


def test_entry_from_raw_with_image_widget_gets_image_modality():
    raw = {
        "endpoint_id": "fal-ai/florence-2-large/detailed-caption",
        "metadata": {
            "category": "vision",
            "display_name": "Florence-2 Large",
            "status": "active",
        },
        "openapi": _minimal_openapi_with_image_url(),
    }
    entry = _entry_from_raw(raw)
    assert entry is not None
    assert "image" in entry.input_modalities
    assert "text" in entry.input_modalities


def test_entry_from_raw_text_only_model_gets_text_only_modality():
    raw = {
        "endpoint_id": "fal-ai/some-llm",
        "metadata": {
            "category": "llm",
            "display_name": "Some LLM",
            "status": "active",
        },
        # no openapi → synthesized widgets, llm category → no image widget
    }
    entry = _entry_from_raw(raw)
    assert entry is not None
    assert entry.input_modalities == ["text"]


# ---- C4: partial fetch must not overwrite a good cache --------------------


_GOOD_RAW = {
    "endpoint_id": "fal-ai/flux/dev",
    "metadata": {
        "category": "text-to-image",
        "display_name": "Flux Dev",
        "status": "active",
    },
}


def test_background_refresh_skips_write_on_partial_fetch():
    """A partial background fetch (completeness=False) must NOT call
    catalog_cache.write — that would shrink an existing good cache."""
    with patch.object(
        model_registry, "_live_fetch", return_value=([_entry_from_raw(_GOOD_RAW)], False)
    ), patch.object(model_registry.catalog_cache, "load_fallback", return_value=[]), \
         patch.object(model_registry.catalog_cache, "write") as write_mock:
        model_registry._refresh_catalog_to_disk()

    write_mock.assert_not_called()


def test_background_refresh_writes_on_complete_fetch():
    """A complete background fetch (completeness=True) DOES write."""
    with patch.object(
        model_registry, "_live_fetch", return_value=([_entry_from_raw(_GOOD_RAW)], True)
    ), patch.object(model_registry.catalog_cache, "load_fallback", return_value=[]), \
         patch.object(model_registry.catalog_cache, "write") as write_mock:
        model_registry._refresh_catalog_to_disk()

    write_mock.assert_called_once()


def test_background_refresh_skips_write_when_live_fetch_fails():
    """When _live_fetch returns (None, False), there's nothing to write."""
    with patch.object(
        model_registry, "_live_fetch", return_value=(None, False)
    ), patch.object(model_registry.catalog_cache, "load_fallback", return_value=[]), \
         patch.object(model_registry.catalog_cache, "write") as write_mock:
        model_registry._refresh_catalog_to_disk()

    write_mock.assert_not_called()


def test_live_fetch_reports_incomplete_when_a_category_partial():
    """_live_fetch threads completeness from fetch_active_video_models."""
    with patch.object(
        model_registry.fal_catalog,
        "fetch_active_video_models",
        return_value=({"text-to-image": [_GOOD_RAW]}, False),
    ):
        models, complete = model_registry._live_fetch()
    assert complete is False
    assert models is not None
    assert models[0].id == "fal-ai/flux/dev"


def _minimal_openapi_with_image_url() -> dict:
    """Smallest valid OpenAPI doc with one image_url property."""
    return {
        "paths": {
            "/": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Input"}
                            }
                        }
                    }
                }
            }
        },
        "components": {
            "schemas": {
                "Input": {
                    "type": "object",
                    "properties": {
                        "image_url": {"type": "string", "_fal_ui_field": "image"},
                        "prompt": {"type": "string"},
                    },
                    "required": ["image_url"],
                }
            }
        },
    }
