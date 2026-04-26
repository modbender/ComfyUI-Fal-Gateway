"""Tests for the `info` STRING output (JSON-encoded fal result dict).

The serialiser is `_serialize_info(result)` in src/nodes/base.py — kept narrow
so it can be unit-tested without ComfyUI runtime.
"""

from __future__ import annotations

import json

from src.nodes.base import _serialize_info


def test_serialize_info_returns_a_string():
    result = {"video": {"url": "https://fal.media/x.mp4"}, "seed": 42}
    info = _serialize_info(result)
    assert isinstance(info, str)


def test_serialize_info_round_trips_dict_keys():
    result = {"seed": 1234, "timings": {"inference_time": 12.5}, "has_nsfw_concepts": [False]}
    info = _serialize_info(result)
    parsed = json.loads(info)
    assert parsed["seed"] == 1234
    assert parsed["timings"]["inference_time"] == 12.5
    assert parsed["has_nsfw_concepts"] == [False]


def test_serialize_info_handles_unicode():
    result = {"prompt": "café — émoji 🎬"}
    info = _serialize_info(result)
    parsed = json.loads(info)
    assert parsed["prompt"] == "café — émoji 🎬"


def test_serialize_info_handles_non_serializable_values_gracefully():
    """Bytes and arbitrary objects shouldn't crash — fall back to repr or skip."""
    result = {"raw_bytes": b"\x00\x01\x02", "seed": 99}
    info = _serialize_info(result)
    # Still valid JSON; the seed should be preserved
    parsed = json.loads(info)
    assert "seed" in parsed
    assert parsed["seed"] == 99


def test_serialize_info_handles_non_dict_input():
    """If fal returns something weird, we don't want a crash."""
    info = _serialize_info(None)
    parsed = json.loads(info)
    assert parsed is None or isinstance(parsed, dict)


def test_serialize_info_includes_url_for_diagnostics():
    """The info should preserve the URL so users can correlate with the saved file."""
    result = {"video": {"url": "https://fal.media/abc.mp4", "duration": 5}}
    info = _serialize_info(result)
    assert "fal.media/abc.mp4" in info
