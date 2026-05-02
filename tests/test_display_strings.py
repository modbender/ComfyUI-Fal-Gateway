"""Tests for the model dropdown display-string helpers.

Format:
  - `[<provider>] <display_name>`                       (default — concise)
  - `[<provider>] <display_name> (<endpoint_id>)`       (collision disambiguator)
  - `[<provider>] <display_name> — <endpoint_id>`       (LEGACY; resolve()
                                                          accepts for back-compat)

The backend stores models keyed by raw endpoint_id, but the dropdown shows
display strings so users can search by provider/family.
"""

from __future__ import annotations

import pytest

from src.model_registry import (
    _build_display_map,
    build_display_string,
    extract_provider,
)
from src.widget_spec import ModelEntry


def _entry(eid: str, display: str = "Some Model") -> ModelEntry:
    return ModelEntry(
        id=eid,
        display_name=display,
        category="text-to-video",
        shape="text_only",
        widgets=[],
    )


# ---- extract_provider -----------------------------------------------------


def test_extract_provider_takes_first_segment_of_path():
    assert extract_provider("fal-ai/flux/dev") == "fal-ai"
    assert extract_provider("bytedance/seedance-2.0/image-to-video") == "bytedance"
    assert extract_provider("xai/grok-imagine-video/image-to-video") == "xai"


def test_extract_provider_handles_single_segment():
    assert extract_provider("flux") == "flux"


def test_extract_provider_handles_deeply_nested_path():
    assert extract_provider("fal-ai/kling-video/v3/pro/image-to-video") == "fal-ai"


def test_extract_provider_handles_empty_string():
    assert extract_provider("") == ""


# ---- build_display_string -------------------------------------------------


def test_build_display_string_includes_provider_and_name():
    e = _entry("bytedance/seedance-2.0/image-to-video", "Seedance 2 Image to Video")
    s = build_display_string(e)
    assert s == "[bytedance] Seedance 2 Image to Video"


def test_build_display_string_omits_endpoint_id_in_short_form():
    """Short form is the default — endpoint_id only appears via collision map."""
    e = _entry("fal-ai/flux/dev", "FLUX.1 [dev]")
    s = build_display_string(e)
    assert " — " not in s, "legacy em-dash + endpoint_id format should be gone"
    assert "fal-ai/flux/dev" not in s


# ---- collision-aware display map ----------------------------------------


def test_display_map_uses_short_form_when_unique():
    entries = [
        _entry("fal-ai/flux/dev", "FLUX dev"),
        _entry("fal-ai/flux/pro", "FLUX pro"),
    ]
    m = _build_display_map(entries)
    assert m["fal-ai/flux/dev"] == "[fal-ai] FLUX dev"
    assert m["fal-ai/flux/pro"] == "[fal-ai] FLUX pro"


def test_display_map_disambiguates_colliding_display_names():
    entries = [
        _entry("fal-ai/kling-video/v2.5/pro/image-to-video", "Kling Video"),
        _entry("fal-ai/kling-video/v3/4k/image-to-video", "Kling Video"),
    ]
    m = _build_display_map(entries)
    # Both entries got disambiguated with their endpoint_id in parens.
    assert m["fal-ai/kling-video/v2.5/pro/image-to-video"] == \
        "[fal-ai] Kling Video (fal-ai/kling-video/v2.5/pro/image-to-video)"
    assert m["fal-ai/kling-video/v3/4k/image-to-video"] == \
        "[fal-ai] Kling Video (fal-ai/kling-video/v3/4k/image-to-video)"


def test_display_map_treats_different_providers_as_non_collisions():
    """Same display name across providers is fine — provider prefix already differs."""
    entries = [
        _entry("fal-ai/foo", "FLUX"),
        _entry("alibaba/bar", "FLUX"),
    ]
    m = _build_display_map(entries)
    assert m["fal-ai/foo"] == "[fal-ai] FLUX"
    assert m["alibaba/bar"] == "[alibaba] FLUX"


# ---- registry.resolve (display-string lookup) -----------------------------


def test_resolve_accepts_short_form_display_string():
    from src import model_registry

    bundled = model_registry.get("fal-ai/bytedance/seedance/v1/lite/image-to-video")
    assert bundled is not None
    display = f"[fal-ai] {bundled.display_name}"
    # Short form may or may not collide with siblings — `resolve` handles both.
    entry = model_registry.resolve(display) or model_registry.resolve(
        f"[fal-ai] {bundled.display_name} ({bundled.id})"
    )
    assert entry is not None
    assert entry.id == bundled.id


def test_resolve_accepts_legacy_long_format():
    """Saved workflows from earlier versions used `[provider] Name — endpoint_id`."""
    from src import model_registry

    bundled = model_registry.get("fal-ai/bytedance/seedance/v1/lite/image-to-video")
    assert bundled is not None
    legacy = f"[fal-ai] {bundled.display_name} — {bundled.id}"
    entry = model_registry.resolve(legacy)
    assert entry is not None
    assert entry.id == bundled.id


def test_resolve_raises_when_unknown_display_string():
    from src import model_registry

    fake = "[fal-ai] Nonexistent Brand New Model"
    with pytest.raises(ValueError, match="didn't resolve"):
        model_registry.resolve(fake)


def test_resolve_raises_on_malformed_input():
    """Values without the [provider] prefix are caller errors."""
    from src import model_registry

    with pytest.raises(ValueError):
        model_registry.resolve("fal-ai/some/raw-id")


def test_resolve_raises_on_empty_input():
    from src import model_registry

    with pytest.raises(ValueError):
        model_registry.resolve("")


def test_resolve_raises_on_non_string():
    from src import model_registry

    with pytest.raises(ValueError):
        model_registry.resolve(None)  # type: ignore[arg-type]
