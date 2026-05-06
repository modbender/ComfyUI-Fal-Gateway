import json
from pathlib import Path
from unittest.mock import patch

from src.openrouter.catalog import (
    fetch_vision_models,
    filter_vision_capable,
    parse_models_response,
)


FIXTURE = Path(__file__).parent / "fixtures" / "openrouter_models.json"


def test_parse_models_response_extracts_id_and_modalities():
    raw = json.loads(FIXTURE.read_text())
    models = parse_models_response(raw)
    assert len(models) > 0
    sample = models[0]
    assert "id" in sample
    assert "input_modalities" in sample
    assert isinstance(sample["input_modalities"], list)


def test_filter_vision_capable_keeps_image_modality():
    models = [
        {"id": "anthropic/claude-3-haiku", "input_modalities": ["text", "image"]},
        {"id": "deepseek/deepseek-v3", "input_modalities": ["text"]},
        {"id": "google/gemini-2.5-pro", "input_modalities": ["text", "image", "file"]},
    ]
    vision = filter_vision_capable(models)
    ids = {m["id"] for m in vision}
    assert ids == {"anthropic/claude-3-haiku", "google/gemini-2.5-pro"}


def test_filter_vision_capable_handles_missing_modalities_field():
    models = [{"id": "weird/model"}]  # no architecture / no modalities
    assert filter_vision_capable(models) == []


def test_fetch_vision_models_returns_empty_on_http_failure():
    """Network down → empty list, never raises (caller decides fallback)."""
    with patch("src.openrouter.catalog._fetch_raw") as m:
        m.side_effect = OSError("network down")
        result = fetch_vision_models()
    assert result == []
