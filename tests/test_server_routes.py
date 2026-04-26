"""Tests for server_routes pure helpers.

The aiohttp route handlers are integration-tested via the running ComfyUI
server. Here we cover the pure logic — base64 decode, padding restoration,
edge cases — so regressions like the padding-stripped bug are caught at unit
test time.
"""

from __future__ import annotations

import base64

import pytest

from src.server_routes import decode_model_id_b64


def _js_btoa_strip_padding(s: str) -> str:
    """Mirror JavaScript's btoa() + URL-safe substitution + padding strip."""
    return (
        base64.b64encode(s.encode("utf-8"))
        .decode("ascii")
        .replace("+", "-")
        .replace("/", "_")
        .rstrip("=")
    )


# ---- the bug we shipped: stripped-padding ids ----------------------------


@pytest.mark.parametrize(
    "model_id",
    [
        "bytedance/seedance-2.0/image-to-video",      # 50 → 2 padding
        "bytedance/seedance-2.0/reference-to-video",  # 55 → 1 padding
        "fal-ai/kling-video/v3/pro/image-to-video",   # 54 → 2 padding
        "fal-ai/kling-video/v2.6/pro/image-to-video", # 56 → 0 padding
        "fal-ai/esrgan",                              # short
        "fal-ai/flux/dev",                            # short
        "x",                                          # tiniest
    ],
)
def test_decode_model_id_b64_round_trips_stripped_padding(model_id):
    encoded = _js_btoa_strip_padding(model_id)
    assert decode_model_id_b64(encoded) == model_id


def test_decode_model_id_b64_handles_already_padded_input():
    """Backend should accept either stripped OR fully-padded input."""
    mid = "bytedance/seedance-2.0/image-to-video"
    padded = base64.urlsafe_b64encode(mid.encode("utf-8")).decode("ascii")
    assert padded.endswith("=="), "fixture sanity: this id should produce 2 padding chars"
    assert decode_model_id_b64(padded) == mid


def test_decode_model_id_b64_handles_unicode_in_id():
    """Some hypothetical model id with non-ASCII characters."""
    mid = "fal-ai/voice/français"
    encoded = _js_btoa_strip_padding(mid)
    assert decode_model_id_b64(encoded) == mid


def test_decode_model_id_b64_raises_on_invalid_base64():
    with pytest.raises(ValueError):
        decode_model_id_b64("not!valid@base64*chars")


def test_decode_model_id_b64_raises_on_invalid_utf8():
    """Bytes that decode but aren't UTF-8 should raise ValueError, not propagate."""
    # base64 of bytes \xff\xfe (not valid UTF-8 lead bytes alone)
    bad = base64.urlsafe_b64encode(b"\xff\xfe").decode("ascii").rstrip("=")
    with pytest.raises(ValueError):
        decode_model_id_b64(bad)


def test_decode_model_id_b64_empty_string_returns_empty():
    """An empty input is valid base64 of an empty string."""
    assert decode_model_id_b64("") == ""
