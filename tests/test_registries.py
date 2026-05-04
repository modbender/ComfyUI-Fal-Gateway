"""Tests for `src/registries/` — curated catalog + live merge dispatch.

Each `CatalogEntry` is one user-facing dropdown row. The registry merges
hand-curated rows with live fal entries (filtered by the category's HIDDEN
set), sorted for type-ahead consistency.
"""

from __future__ import annotations

from src import registries
from src.registries import i2t, t2t
from src.widget_spec import ModelEntry


def _live(eid: str, display: str, category: str = "llm") -> ModelEntry:
    return ModelEntry(
        id=eid,
        display_name=display,
        category=category,
        shape="text_only",
        widgets=[],
    )


# ---- T2T curated catalog --------------------------------------------------


def test_t2t_curated_includes_anthropic_sonnet_45():
    names = [e.display_name for e in t2t.CURATED]
    assert "[Anthropic] Claude Sonnet 4.5" in names


def test_t2t_curated_includes_google_gemini_25_pro():
    names = [e.display_name for e in t2t.CURATED]
    assert "[Google] Gemini 2.5 Pro" in names


def test_t2t_curated_entries_inject_model_via_extra_payload():
    """Each OpenRouter row must carry the raw model id in extra_payload so
    the catalog dispatch path injects it into the request."""
    sonnet = next(e for e in t2t.CURATED if "Sonnet 4.5" in e.display_name)
    assert sonnet.endpoint_id == "openrouter/router/openai/v1/chat/completions"
    assert sonnet.extra_payload == {"model": "anthropic/claude-sonnet-4.5"}


def test_t2t_hidden_endpoints_includes_router_parents():
    assert "openrouter/router/openai/v1/chat/completions" in t2t.HIDDEN_ENDPOINTS
    assert "openrouter/router/openai/v1/responses" in t2t.HIDDEN_ENDPOINTS


# ---- build_catalog merge logic --------------------------------------------


def test_build_catalog_returns_curated_when_no_live_entries():
    out = registries.build_catalog("llm", [])
    assert len(out) == len(t2t.CURATED)


def test_build_catalog_filters_hidden_endpoints_from_live():
    """Live entry whose endpoint_id is in HIDDEN should NOT appear in the
    output — even though it's a "valid" llm category model in fal's catalog."""
    live = [
        _live("openrouter/router/openai/v1/chat/completions", "Chat router"),
        _live("openrouter/router/openai/v1/responses", "Responses router"),
        _live("fal-ai/bytedance/seed/v2/mini", "Seed 2.0 Mini"),
    ]
    out = registries.build_catalog("llm", live)
    endpoint_ids = {e.endpoint_id for e in out}
    assert "fal-ai/bytedance/seed/v2/mini" in endpoint_ids
    # The hidden routers must not surface as standalone rows.
    chat_rows_no_extra = [
        e for e in out
        if e.endpoint_id == "openrouter/router/openai/v1/chat/completions"
        and not e.extra_payload
    ]
    assert chat_rows_no_extra == []


def test_build_catalog_auto_wraps_unknown_live_entries():
    """A live LLM endpoint we don't curate (and isn't in HIDDEN) should
    appear with provider-prefixed display name."""
    live = [_live("nvidia/some-future-llm", "Future LLM")]
    out = registries.build_catalog("llm", live)
    matches = [e for e in out if e.endpoint_id == "nvidia/some-future-llm"]
    assert len(matches) == 1
    assert matches[0].display_name == "[nvidia] Future LLM"
    assert matches[0].provider == "nvidia"
    assert matches[0].extra_payload == {}


def test_build_catalog_results_sorted_by_provider_then_name():
    """Sort key is (provider.lower(), display_name.lower())."""
    out = registries.build_catalog("llm", [])
    providers_in_order = [e.provider for e in out]
    assert providers_in_order == sorted(providers_in_order, key=str.lower)


def test_build_catalog_unknown_category_returns_only_live_entries():
    """A category with no curated registry just wraps live entries."""
    live = [_live("fal-ai/foo", "Foo Model", category="something-else")]
    out = registries.build_catalog("something-else", live)
    assert len(out) == 1
    assert out[0].endpoint_id == "fal-ai/foo"


# ---- I2T catalog ----------------------------------------------------------


def test_i2t_curated_is_empty():
    """Vision endpoints are mostly direct; no curation needed beyond hiding."""
    assert i2t.CURATED == []


def test_i2t_hides_nsfw_classifiers():
    assert "fal-ai/imageutils/nsfw" in i2t.HIDDEN_ENDPOINTS
    assert "fal-ai/x-ailab/nsfw" in i2t.HIDDEN_ENDPOINTS


def test_i2t_hides_video_only_sub_paths():
    assert "fal-ai/sa2va/4b/video" in i2t.HIDDEN_ENDPOINTS
    assert "fal-ai/sa2va/8b/video" in i2t.HIDDEN_ENDPOINTS
    assert "fal-ai/video-understanding" in i2t.HIDDEN_ENDPOINTS


def test_i2t_hides_florence2_duplicates_keeping_detailed_caption():
    assert "fal-ai/florence-2-large/caption" in i2t.HIDDEN_ENDPOINTS
    assert "fal-ai/florence-2-large/more-detailed-caption" in i2t.HIDDEN_ENDPOINTS
    assert "fal-ai/florence-2-large/ocr" in i2t.HIDDEN_ENDPOINTS
    # The canonical Florence row stays (its endpoint isn't in HIDDEN).
    assert "fal-ai/florence-2-large/detailed-caption" not in i2t.HIDDEN_ENDPOINTS


def test_i2t_filters_live_vision_into_useful_subset():
    """Synthetic live list mirroring fal's actual `vision` category — verify
    HIDDEN drops the noise and keeps the caption-shaped models."""
    live = [
        _live("fal-ai/moondream2", "Moondream2", category="vision"),
        _live("fal-ai/moondream2/object-detection", "Moondream2", category="vision"),
        _live("fal-ai/imageutils/nsfw", "NSFW Filter", category="vision"),
        _live("fal-ai/sam-3/image/embed", "Sam 3", category="vision"),
        _live("fal-ai/llava-next", "LLaVA v1.6 34B", category="vision"),
        _live("fal-ai/sa2va/8b/video", "Sa2VA 8B Video", category="vision"),
    ]
    out = registries.build_catalog("vision", live)
    endpoint_ids = {e.endpoint_id for e in out}
    # Kept
    assert "fal-ai/moondream2" in endpoint_ids
    assert "fal-ai/llava-next" in endpoint_ids
    # Dropped (hidden)
    assert "fal-ai/imageutils/nsfw" not in endpoint_ids
    assert "fal-ai/sam-3/image/embed" not in endpoint_ids
    assert "fal-ai/sa2va/8b/video" not in endpoint_ids
    assert "fal-ai/moondream2/object-detection" not in endpoint_ids


# ---- has_curated_catalog dispatcher --------------------------------------


def test_has_curated_catalog_true_for_llm():
    assert registries.has_curated_catalog("llm") is True


def test_has_curated_catalog_true_for_vision():
    """Even an empty curated list (i2t before K2) marks the category as
    catalog-driven so the node uses the dispatch path."""
    assert registries.has_curated_catalog("vision") is True


def test_has_curated_catalog_false_for_video_categories():
    assert registries.has_curated_catalog("text-to-video") is False
    assert registries.has_curated_catalog("image-to-image") is False


# ---- resolve (display_name → CatalogEntry) -------------------------------


def test_resolve_finds_curated_entry_by_display_name():
    out = registries.resolve("llm", "[Anthropic] Claude Sonnet 4.5", [])
    assert out is not None
    assert out.endpoint_id == "openrouter/router/openai/v1/chat/completions"
    assert out.extra_payload["model"] == "anthropic/claude-sonnet-4.5"


def test_resolve_returns_none_for_unknown_display_name():
    assert registries.resolve("llm", "[Made-up] No Such Model", []) is None


def test_resolve_finds_auto_wrapped_live_entry():
    live = [_live("nvidia/nemotron-3", "Nemotron 3")]
    out = registries.resolve("llm", "[nvidia] Nemotron 3", live)
    assert out is not None
    assert out.endpoint_id == "nvidia/nemotron-3"
    assert out.extra_payload == {}
