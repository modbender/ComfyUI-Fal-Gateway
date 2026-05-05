"""Tests for `model_registry._entry_from_raw` pricing plumbing + LLM exclude
patterns + endpoint-override application.
"""

from __future__ import annotations

import json
from pathlib import Path

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
