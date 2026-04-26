"""Tests for the model dropdown display-string helpers.

Format: `[<provider>] <display_name> — <endpoint_id>`

The backend stores models keyed by raw endpoint_id, but the dropdown shows
display strings so users can search by provider/family. We test:
  - format symmetry: build → parse round-trips the endpoint_id
  - the parser tolerates `--` and other dashes in display names
  - provider extraction handles 1-segment and N-segment ids
  - the registry's `resolve` accepts EITHER format (back-compat for saved workflows)
"""

from __future__ import annotations

import pytest

from src.model_registry import (
    build_display_string,
    extract_provider,
    parse_display_string,
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


def test_build_display_string_includes_provider_name_and_endpoint():
    e = _entry("bytedance/seedance-2.0/image-to-video", "Seedance 2 Image to Video")
    s = build_display_string(e)
    assert "[bytedance]" in s
    assert "Seedance 2 Image to Video" in s
    assert "bytedance/seedance-2.0/image-to-video" in s


def test_build_display_string_uses_em_dash_separator():
    """The em-dash is intentional — easier to spot visually and rare in display names."""
    e = _entry("fal-ai/flux/dev", "FLUX.1 [dev]")
    s = build_display_string(e)
    assert " — " in s


# ---- parse_display_string -------------------------------------------------


def test_parse_display_string_round_trips_endpoint_id():
    eid = "bytedance/seedance-2.0/image-to-video"
    e = _entry(eid, "Seedance 2 I2V")
    s = build_display_string(e)
    assert parse_display_string(s) == eid


def test_parse_display_string_handles_display_name_with_internal_dashes():
    """Display names commonly contain dashes — make sure we split on the LAST em-dash."""
    eid = "fal-ai/some/model"
    e = _entry(eid, "Some — fancy — name with — em-dashes")
    s = build_display_string(e)
    assert parse_display_string(s) == eid


def test_parse_display_string_raises_on_raw_endpoint_id():
    """Raw endpoint_ids without the [provider] prefix are rejected."""
    with pytest.raises(ValueError, match="prefix"):
        parse_display_string("bytedance/seedance-2.0/image-to-video")


def test_parse_display_string_raises_on_missing_separator():
    """A string that starts with [provider] but lacks the em-dash separator is invalid."""
    with pytest.raises(ValueError, match="separator"):
        parse_display_string("[bytedance] Seedance 2 with no separator at all")


def test_parse_display_string_raises_on_empty_input():
    with pytest.raises(ValueError):
        parse_display_string("")


def test_parse_display_string_raises_on_non_string():
    with pytest.raises(ValueError):
        parse_display_string(None)  # type: ignore[arg-type]


# ---- registry.resolve (display-string lookup) -----------------------------


def test_resolve_accepts_display_string():
    from src import model_registry

    bundled = model_registry.get("fal-ai/bytedance/seedance/v1/lite/image-to-video")
    assert bundled is not None
    display = build_display_string(bundled)
    entry = model_registry.resolve(display)
    assert entry is not None
    assert entry.id == bundled.id


def test_resolve_returns_none_for_unknown_display_string():
    from src import model_registry

    fake_display = "[fal-ai] Nonexistent Model — fal-ai/nonexistent/model"
    assert model_registry.resolve(fake_display) is None


def test_resolve_raises_on_malformed_input():
    """Malformed values are caller errors — not silent None."""
    from src import model_registry

    with pytest.raises(ValueError):
        model_registry.resolve("fal-ai/some/raw-id")
