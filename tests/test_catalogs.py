"""Tests for `src/catalogs/` — fully-dynamic OpenRouter-driven catalog
plus the live-merge dispatcher.

T2T and I2T both build their `CURATED` list at module-import time by
calling `_openrouter_shared.load_models()` (cache-first, live-fetch
fallback). Tests below patch that loader (or `_build_curated` directly)
to control the input deterministically — no test depends on the actual
OpenRouter API or a real on-disk cache. The fal-direct merge logic in
`catalogs.build_catalog` is exercised independently from the T2T/I2T
build itself.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src import catalogs
from src.catalogs import i2t, t2t
from src.widget_spec import ModelEntry


def _live(eid: str, display: str, category: str = "llm") -> ModelEntry:
    return ModelEntry(
        id=eid,
        display_name=display,
        category=category,
        shape="text_only",
        widgets=[],
    )


def _stub_openrouter_model(
    model_id: str,
    name: str,
    *,
    input_modalities: list[str] | None = None,
    output_modalities: list[str] | None = None,
) -> dict:
    """Shape that mirrors `parse_models_response` output — used in
    tests that mock the shared loader."""
    return {
        "id": model_id,
        "name": name,
        "input_modalities": input_modalities if input_modalities is not None else ["text"],
        "output_modalities": output_modalities if output_modalities is not None else ["text"],
        "description": "",
    }


# ---- T2T dynamic catalog --------------------------------------------------


def test_t2t_curated_built_from_openrouter_cache():
    """T2T CURATED is now derived from the OpenRouter cache, the same way
    I2T already was. Two text-output models in, two `[Vendor] Name` rows
    out, both routing through chat-completions with the model_id in
    extra_payload."""
    cached = [
        _stub_openrouter_model("anthropic/claude-sonnet-4.5", "Claude Sonnet 4.5"),
        _stub_openrouter_model("google/gemini-2.5-pro", "Gemini 2.5 Pro"),
    ]
    with patch("src.catalogs.t2t.load_models", return_value=cached):
        curated = t2t._build_curated()
    ids_by_display = {e.display_name: e.extra_payload.get("model") for e in curated}
    assert ids_by_display.get("[Anthropic] Claude Sonnet 4.5") == "anthropic/claude-sonnet-4.5"
    assert ids_by_display.get("[Google] Gemini 2.5 Pro") == "google/gemini-2.5-pro"
    assert all(
        e.endpoint_id == "openrouter/router/openai/v1/chat/completions"
        for e in curated
    )


def test_t2t_curated_is_empty_when_openrouter_cache_empty():
    """First-start-offline case: loader returns []. CURATED build must
    not crash and must yield an empty list (T2T dropdown shows only
    fal-direct entries via the live merge)."""
    with patch("src.catalogs.t2t.load_models", return_value=[]):
        assert t2t._build_curated() == []


def test_t2t_curated_filters_out_models_without_text_output_defensively():
    """A model that exists on OpenRouter but only outputs images
    (e.g. `gpt-5-image`) or only audio doesn't belong in the chat
    dropdown — filter_text_capable drops it."""
    cached = [
        _stub_openrouter_model("anthropic/claude-sonnet-4.5", "Claude Sonnet 4.5"),
        _stub_openrouter_model(
            "openai/gpt-5-image", "GPT-5 Image",
            input_modalities=["text"], output_modalities=["image"],
        ),
        _stub_openrouter_model(
            "openai/gpt-audio", "GPT Audio",
            input_modalities=["text"], output_modalities=["audio"],
        ),
    ]
    with patch("src.catalogs.t2t.load_models", return_value=cached):
        curated = t2t._build_curated()
    model_ids = {e.extra_payload["model"] for e in curated}
    assert model_ids == {"anthropic/claude-sonnet-4.5"}


def test_t2t_curated_has_no_hardcoded_model_ids_in_source():
    """Regression canary: the previous version of this catalog hardcoded
    30 `_openrouter(...)` calls with literal model IDs that rotted as
    OpenRouter deprecated models. Pin the no-hardcoding invariant by
    grepping the source.

    Failure here means someone re-introduced hardcoded entries.
    """
    src_path = Path(__file__).resolve().parent.parent / "src" / "catalogs" / "t2t.py"
    source = src_path.read_text(encoding="utf-8")
    assert "_openrouter(" not in source, (
        "src/catalogs/t2t.py must NOT define hardcoded _openrouter(...) "
        "entries — catalog is built dynamically via _build_curated()"
    )
    # No hardcoded vendor/model strings. (HIDDEN_ENDPOINTS is endpoint
    # IDs, not OpenRouter model IDs — only the protocol routers.)
    for vendor in ("anthropic/claude", "google/gemini", "deepseek/", "x-ai/", "openai/gpt", "mistralai/"):
        assert vendor not in source, (
            f"hardcoded vendor-prefixed model string '{vendor}' found in t2t.py — "
            "all model IDs must come from the OpenRouter cache at runtime"
        )


def test_t2t_hidden_endpoints_includes_router_parents():
    assert "openrouter/router/openai/v1/chat/completions" in t2t.HIDDEN_ENDPOINTS
    assert "openrouter/router/openai/v1/responses" in t2t.HIDDEN_ENDPOINTS


# ---- build_catalog merge logic --------------------------------------------


def test_build_catalog_returns_curated_when_no_live_entries():
    """With a stubbed CURATED of known size, build_catalog with empty live
    just returns the curated entries (the merge filter is identity here)."""
    cached = [
        _stub_openrouter_model("anthropic/claude-sonnet-4.5", "Claude Sonnet 4.5"),
        _stub_openrouter_model("google/gemini-2.5-pro", "Gemini 2.5 Pro"),
    ]
    with patch("src.catalogs.t2t.load_models", return_value=cached):
        stubbed = t2t._build_curated()
    with patch.object(t2t, "CURATED", stubbed):
        out = catalogs.build_catalog("llm", [])
    assert len(out) == len(stubbed)


def test_build_catalog_filters_hidden_endpoints_from_live():
    """Live entry whose endpoint_id is in HIDDEN should NOT appear in the
    output — even though it's a "valid" llm category model in fal's catalog."""
    live = [
        _live("openrouter/router/openai/v1/chat/completions", "Chat router"),
        _live("openrouter/router/openai/v1/responses", "Responses router"),
        _live("fal-ai/bytedance/seed/v2/mini", "Seed 2.0 Mini"),
    ]
    out = catalogs.build_catalog("llm", live)
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
    out = catalogs.build_catalog("llm", live)
    matches = [e for e in out if e.endpoint_id == "nvidia/some-future-llm"]
    assert len(matches) == 1
    assert matches[0].display_name == "[nvidia] Future LLM"
    assert matches[0].provider == "nvidia"
    assert matches[0].extra_payload == {}


def test_build_catalog_results_sorted_by_provider_then_name():
    """Sort key is (provider.lower(), display_name.lower())."""
    out = catalogs.build_catalog("llm", [])
    providers_in_order = [e.provider for e in out]
    assert providers_in_order == sorted(providers_in_order, key=str.lower)


def test_build_catalog_unknown_category_returns_only_live_entries():
    """A category with no curated registry just wraps live entries."""
    live = [_live("fal-ai/foo", "Foo Model", category="something-else")]
    out = catalogs.build_catalog("something-else", live)
    assert len(out) == 1
    assert out[0].endpoint_id == "fal-ai/foo"


# ---- I2T catalog ----------------------------------------------------------


def test_i2t_curated_built_from_openrouter_cache():
    """When openrouter cache has vision models, CURATED includes them."""
    cached = [
        _stub_openrouter_model(
            "anthropic/claude-sonnet-4.5", "Claude Sonnet 4.5",
            input_modalities=["text", "image"],
        ),
        _stub_openrouter_model(
            "google/gemini-2.5-pro", "Gemini 2.5 Pro",
            input_modalities=["text", "image"],
        ),
    ]
    with patch("src.catalogs.i2t.load_models", return_value=cached):
        curated = i2t._build_curated()
    ids_by_display = {e.display_name: e.extra_payload.get("model") for e in curated}
    assert ids_by_display.get("[Anthropic] Claude Sonnet 4.5") == "anthropic/claude-sonnet-4.5"
    assert ids_by_display.get("[Google] Gemini 2.5 Pro") == "google/gemini-2.5-pro"
    assert all(e.endpoint_id == "openrouter/router/vision" for e in curated)
    assert all(e.provider in ("anthropic", "google") for e in curated)


def test_i2t_curated_is_empty_when_openrouter_cache_empty():
    with patch("src.catalogs.i2t.load_models", return_value=[]):
        assert i2t._build_curated() == []


def test_i2t_curated_filters_non_vision_models_defensively():
    """Text-only models in the cache must NOT surface in I2T (vision-only)."""
    cached = [
        _stub_openrouter_model(
            "anthropic/claude-sonnet-4.5", "Claude Sonnet 4.5",
            input_modalities=["text", "image"],
        ),
        _stub_openrouter_model(
            "deepseek/deepseek-v3.2", "DeepSeek V3.2",
            input_modalities=["text"],
        ),
    ]
    with patch("src.catalogs.i2t.load_models", return_value=cached):
        curated = i2t._build_curated()
    assert len(curated) == 1
    assert curated[0].extra_payload["model"] == "anthropic/claude-sonnet-4.5"


def _hidden_by_i2t(endpoint_id: str) -> bool:
    """Mirror of catalogs.build_catalog's hide check — exact + suffix."""
    if endpoint_id in i2t.HIDDEN_ENDPOINTS:
        return True
    return endpoint_id.endswith(i2t.HIDDEN_ENDPOINT_SUFFIXES)


def test_i2t_hides_nsfw_classifiers():
    # The `/nsfw` suffix rule catches every vendor's NSFW endpoint without
    # requiring per-endpoint maintenance.
    assert _hidden_by_i2t("fal-ai/imageutils/nsfw")
    assert _hidden_by_i2t("fal-ai/x-ailab/nsfw")


def test_i2t_hides_video_only_sub_paths():
    assert _hidden_by_i2t("fal-ai/sa2va/4b/video")
    assert _hidden_by_i2t("fal-ai/sa2va/8b/video")


def test_i2t_hides_florence2_duplicates_keeping_detailed_caption():
    # Duplicate short/long caption variants — kept as exact entries because
    # they don't fit a clean suffix pattern.
    assert _hidden_by_i2t("fal-ai/florence-2-large/caption")
    assert _hidden_by_i2t("fal-ai/florence-2-large/more-detailed-caption")
    # OCR variants caught by the `/ocr` suffix rule.
    assert _hidden_by_i2t("fal-ai/florence-2-large/ocr")
    # The canonical Florence row stays.
    assert not _hidden_by_i2t("fal-ai/florence-2-large/detailed-caption")


def test_i2t_suffix_rules_catch_new_noise_endpoints_without_maintenance():
    """The suffix list is the maintenance-free half of the filter — when
    fal ships a new `/embed`, `/detect`, `/batch`, etc. it gets hidden
    automatically. Regression canary: if someone deletes a suffix and
    re-introduces the explicit list, this fails."""
    # Caught by suffix rules — no exact-list entry needed.
    assert _hidden_by_i2t("fal-ai/moondream3-preview/detect")
    assert _hidden_by_i2t("fal-ai/moondream3-preview/point")
    assert _hidden_by_i2t("fal-ai/moondream3-preview/query")
    assert _hidden_by_i2t("fal-ai/sam-3/image/embed")
    assert _hidden_by_i2t("fal-ai/clip-embeddings")
    assert _hidden_by_i2t("fal-ai/florence-2-large/open-vocabulary-detection")
    assert _hidden_by_i2t("fal-ai/florence-2-large/region-proposal")
    assert _hidden_by_i2t("fal-ai/florence-2-large/referring-expression-segmentation")


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
    out = catalogs.build_catalog("vision", live)
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
    assert catalogs.has_curated_catalog("llm") is True


def test_has_curated_catalog_true_for_vision():
    """Even an empty curated list marks the category as catalog-driven
    so the node uses the dispatch path."""
    assert catalogs.has_curated_catalog("vision") is True


def test_has_curated_catalog_false_for_video_categories():
    assert catalogs.has_curated_catalog("text-to-video") is False
    assert catalogs.has_curated_catalog("image-to-image") is False


# ---- resolve (display_name → CatalogEntry) -------------------------------


def test_resolve_finds_curated_entry_by_display_name():
    """resolve() iterates the merged catalog. Mock CURATED so the test
    doesn't depend on what's currently in the OpenRouter cache."""
    cached = [
        _stub_openrouter_model("anthropic/claude-sonnet-4.5", "Claude Sonnet 4.5"),
    ]
    with patch("src.catalogs.t2t.load_models", return_value=cached):
        stubbed = t2t._build_curated()
    with patch.object(t2t, "CURATED", stubbed):
        out = catalogs.resolve("llm", "[Anthropic] Claude Sonnet 4.5", [])
    assert out is not None
    assert out.endpoint_id == "openrouter/router/openai/v1/chat/completions"
    assert out.extra_payload["model"] == "anthropic/claude-sonnet-4.5"


def test_resolve_returns_none_for_unknown_display_name():
    assert catalogs.resolve("llm", "[Made-up] No Such Model", []) is None


def test_resolve_finds_auto_wrapped_live_entry():
    live = [_live("nvidia/nemotron-3", "Nemotron 3")]
    out = catalogs.resolve("llm", "[nvidia] Nemotron 3", live)
    assert out is not None
    assert out.endpoint_id == "nvidia/nemotron-3"
    assert out.extra_payload == {}
