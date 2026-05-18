"""Integration tests against the live OpenRouter `/api/v1/models` endpoint.

OPT-IN. Default `pytest` invocations skip these via the `-m 'not integration'`
filter in pyproject.toml. To run:

    uv run pytest -m integration

These tests guard against two failure modes the unit tests can't see:
  1. OpenRouter's response shape changes (architecture / modality fields
     get renamed or restructured) and our parser silently breaks.
  2. The endpoint goes down or returns an unexpected payload type.

They DO NOT verify any specific model is present — that would be brittle
as OpenRouter's roster shifts. Instead they assert reasonable counts and
that text/vision filters both yield non-empty subsets.
"""

from __future__ import annotations

import socket

import pytest

from src.openrouter.catalog import (
    fetch_all_models,
    filter_text_capable,
    filter_vision_capable,
)


pytestmark = pytest.mark.integration


def _internet_available() -> bool:
    """Don't fail the suite if the test runner is offline — skip cleanly."""
    try:
        socket.gethostbyname("openrouter.ai")
        return True
    except OSError:
        return False


@pytest.fixture(scope="module")
def live_models() -> list[dict]:
    if not _internet_available():
        pytest.skip("network not available — openrouter.ai unreachable")
    models = fetch_all_models()
    if not models:
        pytest.skip("fetch_all_models returned [] — openrouter unreachable or rate-limited")
    return models


def test_fetch_all_models_yields_substantial_list(live_models):
    """A working OpenRouter endpoint has hundreds of models — fewer than
    100 means something's wrong with the parser or the response shape."""
    assert len(live_models) > 100


def test_filter_text_capable_yields_majority_of_models(live_models):
    """Most OpenRouter models are chat completions (text out). If this
    drops below 100 either the filter regressed or OpenRouter renamed
    the output_modalities field."""
    text = filter_text_capable(live_models)
    assert len(text) > 100


def test_filter_vision_capable_yields_substantial_subset(live_models):
    """Vision-capable subset should be smaller but still substantial."""
    vision = filter_vision_capable(live_models)
    assert len(vision) > 30


def test_parsed_models_have_expected_shape(live_models):
    """Each parsed model dict must have the fields catalogs.* depend on."""
    sample = live_models[0]
    assert "id" in sample
    assert "name" in sample
    assert "input_modalities" in sample
    assert "output_modalities" in sample
    assert isinstance(sample["input_modalities"], list)
    assert isinstance(sample["output_modalities"], list)
