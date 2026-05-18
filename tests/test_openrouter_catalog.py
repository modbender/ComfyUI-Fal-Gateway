"""Tests for `src/openrouter/catalog.py` — parse, modality filters,
unfiltered fetch, and vision convenience wrapper."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from src.openrouter.catalog import (
    fetch_all_models,
    fetch_vision_models,
    filter_text_capable,
    filter_vision_capable,
    parse_models_response,
)


FIXTURE = Path(__file__).parent / "fixtures" / "openrouter_models.json"


def test_parse_models_response_extracts_id_modalities_and_output_modalities():
    raw = json.loads(FIXTURE.read_text())
    models = parse_models_response(raw)
    assert len(models) > 0
    sample = models[0]
    assert "id" in sample
    assert "input_modalities" in sample
    assert "output_modalities" in sample
    assert isinstance(sample["input_modalities"], list)
    assert isinstance(sample["output_modalities"], list)


def test_filter_vision_capable_keeps_image_modality():
    # Use placeholder vendor names so the test isn't pinned to real,
    # potentially-deprecated OpenRouter IDs — the filter cares about
    # the modality field, not the ID format.
    models = [
        {"id": "vendor-a/multimodal-model", "input_modalities": ["text", "image"]},
        {"id": "vendor-b/text-only-model", "input_modalities": ["text"]},
        {"id": "vendor-c/multimodal-with-file", "input_modalities": ["text", "image", "file"]},
    ]
    vision = filter_vision_capable(models)
    ids = {m["id"] for m in vision}
    assert ids == {"vendor-a/multimodal-model", "vendor-c/multimodal-with-file"}


def test_filter_vision_capable_handles_missing_modalities_field():
    models = [{"id": "weird/model"}]  # no architecture / no modalities
    assert filter_vision_capable(models) == []


def test_filter_text_capable_keeps_text_output_modality():
    """T2T needs models that output text. Image-output-only and audio-only
    models in OpenRouter's list (gpt-5-image, gpt-audio, ...) must drop."""
    models = [
        {"id": "vendor/chat-model", "output_modalities": ["text"]},
        {"id": "vendor/image-gen", "output_modalities": ["image"]},
        {"id": "vendor/tts", "output_modalities": ["audio"]},
        {"id": "vendor/mixed", "output_modalities": ["text", "image"]},
    ]
    text = filter_text_capable(models)
    ids = {m["id"] for m in text}
    assert ids == {"vendor/chat-model", "vendor/mixed"}


def test_filter_text_capable_handles_missing_output_modalities():
    """Missing `output_modalities` is treated as not-text — defensive default."""
    models = [{"id": "weird/no-arch"}]
    assert filter_text_capable(models) == []


def test_fetch_all_models_returns_full_unfiltered_list_on_success():
    """Stubs the HTTP layer — verifies fetch returns the parsed list
    without any modality filtering applied."""
    raw_payload = {
        "data": [
            {"id": "vendor/text-model", "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}},
            {"id": "vendor/vision-model", "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]}},
            {"id": "vendor/image-model", "architecture": {"input_modalities": ["text"], "output_modalities": ["image"]}},
        ],
    }
    with patch("src.openrouter.catalog._fetch_raw", return_value=raw_payload):
        result = fetch_all_models()
    assert len(result) == 3
    assert {m["id"] for m in result} == {"vendor/text-model", "vendor/vision-model", "vendor/image-model"}


def test_fetch_all_models_returns_empty_on_http_failure():
    """Network down → empty list, never raises (caller decides fallback)."""
    with patch("src.openrouter.catalog._fetch_raw") as m:
        m.side_effect = OSError("network down")
        result = fetch_all_models()
    assert result == []


def test_fetch_vision_models_returns_empty_on_http_failure():
    """Vision convenience wrapper inherits the same failure mode."""
    with patch("src.openrouter.catalog._fetch_raw") as m:
        m.side_effect = OSError("network down")
        result = fetch_vision_models()
    assert result == []


def test_fixture_yields_many_text_capable_models_sanity():
    """Sanity check on the fixture itself: a refreshed openrouter_models.json
    should yield >100 text-capable models. Catches a truncated or corrupted
    fixture before it ships."""
    raw = json.loads(FIXTURE.read_text())
    models = parse_models_response(raw)
    text = filter_text_capable(models)
    assert len(text) > 100, (
        f"fixture only yields {len(text)} text-capable models — expected >100. "
        "Refresh tests/fixtures/openrouter_models.json from live OpenRouter."
    )
