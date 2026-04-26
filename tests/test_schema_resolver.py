"""Tests for schema_resolver: OpenAPI 3.0 → WidgetSpec list + shape detection.

Fixtures are real fal catalog entries captured at test-write time. They live
in tests/fixtures/.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.schema_resolver import ParsedSchema, SchemaError, parse_openapi


_FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(_FIXTURE_DIR / name, encoding="utf-8") as f:
        model = json.load(f)
    return model["openapi"]


def _parse(name: str, category: str) -> ParsedSchema:
    return parse_openapi(_load_fixture(name), category)


def _by_name(parsed: ParsedSchema):
    return {w.name: w for w in parsed.widgets}


# ----- T2V (text only) ---------------------------------------------------


def test_seedance_t2v_basic_shape():
    p = _parse("bytedance_seedance_2.0_text_to_video.json", "text-to-video")
    assert p.shape == "text_only"


def test_seedance_t2v_includes_prompt_required():
    p = _parse("bytedance_seedance_2.0_text_to_video.json", "text-to-video")
    prompt = _by_name(p)["prompt"]
    assert prompt.kind == "STRING"
    assert prompt.required is True
    assert prompt.multiline is True


def test_seedance_t2v_string_enum_becomes_combo():
    p = _parse("bytedance_seedance_2.0_text_to_video.json", "text-to-video")
    by = _by_name(p)
    aspect = by["aspect_ratio"]
    assert aspect.kind == "COMBO"
    assert "16:9" in aspect.options


def test_seedance_t2v_anyOf_nullable_integer_seed():
    p = _parse("bytedance_seedance_2.0_text_to_video.json", "text-to-video")
    seed = _by_name(p)["seed"]
    assert seed.kind == "INT"
    assert seed.required is False


def test_seedance_t2v_boolean_generate_audio():
    p = _parse("bytedance_seedance_2.0_text_to_video.json", "text-to-video")
    g = _by_name(p)["generate_audio"]
    assert g.kind == "BOOLEAN"
    assert isinstance(g.default, bool)


# ----- I2V with optional end image (FLF) --------------------------------


def test_seedance_i2v_detects_flf_shape_via_end_image_url():
    p = _parse("bytedance_seedance_2.0_image_to_video.json", "image-to-video")
    assert p.shape == "flf", f"expected flf, got {p.shape!r}"


def test_seedance_i2v_image_url_required():
    p = _parse("bytedance_seedance_2.0_image_to_video.json", "image-to-video")
    img = _by_name(p)["image_url"]
    assert img.kind == "IMAGE_INPUT"
    assert img.required is True
    assert img.payload_key == "image_url"


def test_seedance_i2v_end_image_url_optional():
    p = _parse("bytedance_seedance_2.0_image_to_video.json", "image-to-video")
    end = _by_name(p)["end_image_url"]
    assert end.kind == "IMAGE_INPUT"
    assert end.required is False


# ----- Kling 1.6 Pro I2V (tail_image_url FLF variant) -------------------


def test_kling_v16_pro_i2v_detects_flf_shape_via_tail_image_url():
    p = _parse("fal_ai_kling_video_v1.6_pro_image_to_video.json", "image-to-video")
    assert p.shape == "flf", f"expected flf, got {p.shape!r}"


def test_kling_v16_pro_i2v_image_url_required():
    p = _parse("fal_ai_kling_video_v1.6_pro_image_to_video.json", "image-to-video")
    by = _by_name(p)
    assert by["image_url"].kind == "IMAGE_INPUT"
    assert by["image_url"].required is True
    assert by["tail_image_url"].kind == "IMAGE_INPUT"
    assert by["tail_image_url"].required is False


def test_kling_v16_pro_i2v_negative_prompt_multiline_with_default():
    p = _parse("fal_ai_kling_video_v1.6_pro_image_to_video.json", "image-to-video")
    nprompt = _by_name(p)["negative_prompt"]
    assert nprompt.kind == "STRING"
    assert nprompt.multiline is True
    assert nprompt.default and "blur" in nprompt.default


def test_kling_v16_pro_i2v_cfg_scale_float_with_min_max():
    p = _parse("fal_ai_kling_video_v1.6_pro_image_to_video.json", "image-to-video")
    cfg = _by_name(p)["cfg_scale"]
    assert cfg.kind == "FLOAT"
    assert cfg.meta.get("min") == 0
    assert cfg.meta.get("max") == 1
    assert cfg.default == 0.5


def test_kling_v16_pro_i2v_duration_combo():
    p = _parse("fal_ai_kling_video_v1.6_pro_image_to_video.json", "image-to-video")
    dur = _by_name(p)["duration"]
    assert dur.kind == "COMBO"
    assert set(dur.options) == {"5", "10"}


# ----- Seedance 2 Reference-to-Video (multi_ref via image_urls array) --


def test_seedance_reference_to_video_detects_multi_ref():
    p = _parse("bytedance_seedance_2.0_reference_to_video.json", "image-to-video")
    assert p.shape == "multi_ref", f"expected multi_ref, got {p.shape!r}"


def test_seedance_reference_to_video_image_urls_is_image_array():
    p = _parse("bytedance_seedance_2.0_reference_to_video.json", "image-to-video")
    image_urls = _by_name(p)["image_urls"]
    assert image_urls.kind == "IMAGE_ARRAY"


# ----- MiniMax subject-reference (single_image with non-standard name) -


def test_minimax_subject_reference_detects_image_via_name_heuristic():
    p = _parse("fal_ai_minimax_video_01_subject_reference.json", "image-to-video")
    by = _by_name(p)
    img = by["subject_reference_image_url"]
    assert img.kind == "IMAGE_INPUT"
    assert img.required is True


def test_minimax_subject_reference_shape_is_single_image():
    p = _parse("fal_ai_minimax_video_01_subject_reference.json", "image-to-video")
    # Single image-typed input → single_image (not flf, not multi_ref)
    assert p.shape == "single_image"


# ----- Edge cases --------------------------------------------------------


def test_missing_post_endpoint_raises_schema_error():
    bad = {"openapi": "3.0.0", "info": {"title": "X"}, "paths": {}, "components": {"schemas": {}}}
    with pytest.raises(SchemaError):
        parse_openapi(bad, "image-to-video")


def test_t2i_baseline_flux_dev_classified_as_text_only():
    """Baseline T2I shouldn't be confused with anything else."""
    p = _parse("fal_ai_flux_dev.json", "text-to-image")
    assert p.shape == "text_only"


# ----- Upscale detection (E2) -----------------------------------------------


def test_upscale_detected_via_upscaling_tag_on_esrgan():
    fx = _load_fixture("fal_ai_esrgan.json")
    raw = json.loads((_FIXTURE_DIR / "fal_ai_esrgan.json").read_text())
    meta = raw["metadata"]
    p = parse_openapi(fx, "image-to-image", metadata=meta, endpoint_id=raw["endpoint_id"])
    assert p.shape == "upscale", f"esrgan should be upscale, got {p.shape!r}"


def test_upscale_detected_on_clarity_upscaler_via_tag():
    fx = _load_fixture("fal_ai_clarity_upscaler.json")
    raw = json.loads((_FIXTURE_DIR / "fal_ai_clarity_upscaler.json").read_text())
    p = parse_openapi(fx, "image-to-image", metadata=raw["metadata"], endpoint_id=raw["endpoint_id"])
    assert p.shape == "upscale"


def test_upscale_detected_on_crystal_upscaler_via_endpoint_name():
    """Crystal-upscaler has no 'upscaling' tag, only the name signal — endpoint regex catches it."""
    fx = _load_fixture("clarityai_crystal_upscaler.json")
    raw = json.loads((_FIXTURE_DIR / "clarityai_crystal_upscaler.json").read_text())
    p = parse_openapi(fx, "image-to-image", metadata=raw["metadata"], endpoint_id=raw["endpoint_id"])
    assert p.shape == "upscale"


def test_upscale_detected_via_description_keyword():
    """Synthetic case: no tag, no name match, but description mentions 'super-resolution'."""
    fake_oa = _build_minimal_image_to_image_openapi()
    p = parse_openapi(
        fake_oa,
        "image-to-image",
        metadata={"tags": [], "description": "A super-resolution model that enlarges images."},
        endpoint_id="fal-ai/some-vendor/sr-magic",
    )
    assert p.shape == "upscale"


def test_image_to_image_model_without_upscale_signals_is_single_image():
    """Synthetic case: regular I2I model (style transfer) should NOT be upscale."""
    fake_oa = _build_minimal_image_to_image_openapi()
    p = parse_openapi(
        fake_oa,
        "image-to-image",
        metadata={"tags": ["style-transfer", "image-to-image"], "description": "Apply artistic style to images."},
        endpoint_id="fal-ai/some-vendor/style-transfer",
    )
    assert p.shape == "single_image"


def test_text_to_image_with_upscale_in_tags_is_still_text_only():
    """Upscale check only applies to image-to-image category."""
    fake_oa = _build_minimal_text_to_image_openapi()
    p = parse_openapi(
        fake_oa,
        "text-to-image",
        metadata={"tags": ["upscaling"], "description": "Generate upscaled-quality images from text."},
        endpoint_id="fal-ai/some-vendor/upscale-aware-t2i",
    )
    assert p.shape == "text_only"


def test_parse_openapi_works_without_metadata_kwarg_for_backwards_compat():
    """Existing callers that don't pass metadata should still work."""
    fx = _load_fixture("fal_ai_esrgan.json")
    p = parse_openapi(fx, "image-to-image")
    # Without metadata, upscale heuristic can't fire on tag/description; falls back to single_image
    # (esrgan has only 1 IMAGE_INPUT in its schema). That's expected, NOT a bug.
    assert p.shape in ("single_image", "upscale")


def _build_minimal_image_to_image_openapi() -> dict:
    return {
        "openapi": "3.0.0",
        "info": {"title": "Test", "version": "1"},
        "paths": {
            "/x": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Input"}}
                        }
                    }
                }
            }
        },
        "components": {
            "schemas": {
                "Input": {
                    "type": "object",
                    "required": ["prompt", "image_url"],
                    "properties": {
                        "prompt": {"type": "string"},
                        "image_url": {"type": "string"},
                    },
                }
            }
        },
    }


def _build_minimal_text_to_image_openapi() -> dict:
    return {
        "openapi": "3.0.0",
        "info": {"title": "Test", "version": "1"},
        "paths": {
            "/x": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Input"}}
                        }
                    }
                }
            }
        },
        "components": {
            "schemas": {
                "Input": {
                    "type": "object",
                    "required": ["prompt"],
                    "properties": {"prompt": {"type": "string"}},
                }
            }
        },
    }


def test_text_to_video_with_image_field_still_text_only_shape():
    """category overrides shape — a T2V model with a non-image field that happens to
    contain the word 'image' (e.g. 'reference_image_strength') should not be misclassified."""
    # Synthetic minimal T2V schema
    fake = {
        "openapi": "3.0.0",
        "info": {"title": "Test", "version": "1"},
        "paths": {
            "/x": {
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
                    "required": ["prompt"],
                    "properties": {
                        "prompt": {"type": "string"},
                        "image_strength": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5},
                    },
                }
            }
        },
    }
    p = parse_openapi(fake, "text-to-video")
    assert p.shape == "text_only"
    by = _by_name(p)
    assert by["image_strength"].kind == "FLOAT"
