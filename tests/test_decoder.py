"""Tests for src.fal.decoder: image bytes → tensor decode + result-URL extraction.

Tests generate image bytes inline via PIL — no on-disk fixtures needed.
Network-bound `fetch_image_as_tensor` and `decode_artifact` integration paths
are exercised via the integration suite (see tests/integration/) since they
require live HTTP. Here we cover the decoder + URL-extraction logic.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from src.fal.decoder import (
    _decode_image_bytes_to_tensor,
    _image_url_from_result,
    extract_artifact_url,
)


# ---- helpers ---------------------------------------------------------------


def _png_bytes(w: int, h: int, color=(255, 0, 0), mode: str = "RGB") -> bytes:
    img = Image.new(mode, (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes(w: int, h: int, color=(0, 255, 0)) -> bytes:
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _webp_bytes(w: int, h: int, color=(0, 0, 255)) -> bytes:
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=95)
    return buf.getvalue()


# ---- _image_url_from_result -----------------------------------------------


def test_image_url_from_result_handles_images_array():
    result = {"images": [{"url": "https://fal.media/foo.png", "width": 512, "height": 512}]}
    assert _image_url_from_result(result) == "https://fal.media/foo.png"


def test_image_url_from_result_handles_image_object():
    result = {"image": {"url": "https://fal.media/bar.jpg"}}
    assert _image_url_from_result(result) == "https://fal.media/bar.jpg"


def test_image_url_from_result_handles_output_object():
    result = {"output": {"url": "https://fal.media/baz.png"}}
    assert _image_url_from_result(result) == "https://fal.media/baz.png"


def test_image_url_from_result_handles_output_array():
    result = {"output": [{"url": "https://fal.media/qux.png"}, {"url": "second.png"}]}
    assert _image_url_from_result(result) == "https://fal.media/qux.png"


def test_image_url_from_result_handles_top_level_url():
    result = {"url": "https://fal.media/direct.png"}
    assert _image_url_from_result(result) == "https://fal.media/direct.png"


def test_image_url_from_result_raises_on_unknown_shape():
    result = {"foo": "bar", "baz": 42}
    with pytest.raises(RuntimeError) as exc_info:
        _image_url_from_result(result)
    # Error should mention the actual top-level keys for diagnosis
    assert "foo" in str(exc_info.value) or "baz" in str(exc_info.value)


def test_image_url_from_result_raises_on_empty_images_array():
    result = {"images": []}
    with pytest.raises(RuntimeError):
        _image_url_from_result(result)


def test_image_url_from_result_skips_image_entry_without_url():
    """An images entry that's an empty dict should be ignored, falling through."""
    result = {"images": [{}, {"url": "https://fal.media/second.png"}]}
    assert _image_url_from_result(result) == "https://fal.media/second.png"


# ---- extract_artifact_url --------------------------------------------------


def test_extract_artifact_url_dispatches_video():
    result = {"video": {"url": "https://fal.media/clip.mp4"}}
    assert extract_artifact_url(result, "video") == "https://fal.media/clip.mp4"


def test_extract_artifact_url_dispatches_image():
    result = {"images": [{"url": "https://fal.media/pic.png"}]}
    assert extract_artifact_url(result, "image") == "https://fal.media/pic.png"


def test_extract_artifact_url_raises_for_unknown_kind():
    with pytest.raises(NotImplementedError):
        extract_artifact_url({}, "audio")


# ---- _decode_image_bytes_to_tensor ----------------------------------------


def test_decode_image_bytes_handles_png():
    import torch

    data = _png_bytes(8, 4, color=(255, 0, 0))
    tensor = _decode_image_bytes_to_tensor(data)
    # Expect [1, H, W, 3] float32 in [0, 1]
    assert tensor.shape == (1, 4, 8, 3)
    assert tensor.dtype == torch.float32
    arr = tensor[0].cpu().numpy() if hasattr(tensor[0], "cpu") else tensor[0]
    # Pure red: R≈1, G≈0, B≈0
    np.testing.assert_allclose(arr[:, :, 0], 1.0, atol=0.01)
    np.testing.assert_allclose(arr[:, :, 1], 0.0, atol=0.01)
    np.testing.assert_allclose(arr[:, :, 2], 0.0, atol=0.01)


def test_decode_image_bytes_handles_jpeg():
    data = _jpeg_bytes(16, 16, color=(0, 255, 0))
    tensor = _decode_image_bytes_to_tensor(data)
    assert tensor.shape == (1, 16, 16, 3)
    arr = tensor[0].cpu().numpy() if hasattr(tensor[0], "cpu") else tensor[0]
    np.testing.assert_allclose(arr[:, :, 1], 1.0, atol=0.05)  # JPEG lossy


def test_decode_image_bytes_handles_webp():
    data = _webp_bytes(8, 8, color=(0, 0, 255))
    tensor = _decode_image_bytes_to_tensor(data)
    assert tensor.shape == (1, 8, 8, 3)
    arr = tensor[0].cpu().numpy() if hasattr(tensor[0], "cpu") else tensor[0]
    np.testing.assert_allclose(arr[:, :, 2], 1.0, atol=0.05)


def test_decode_image_bytes_promotes_grayscale_to_rgb():
    img = Image.new("L", (4, 4), 128)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    tensor = _decode_image_bytes_to_tensor(buf.getvalue())
    assert tensor.shape == (1, 4, 4, 3)
    arr = tensor[0].cpu().numpy() if hasattr(tensor[0], "cpu") else tensor[0]
    # All three channels should be equal (grayscale duplicated)
    np.testing.assert_allclose(arr[:, :, 0], arr[:, :, 1], atol=0.01)
    np.testing.assert_allclose(arr[:, :, 1], arr[:, :, 2], atol=0.01)


def test_decode_image_bytes_drops_alpha_channel():
    """RGBA PNG should be returned as 3-channel RGB (alpha discarded)."""
    img = Image.new("RGBA", (4, 4), (255, 100, 50, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    tensor = _decode_image_bytes_to_tensor(buf.getvalue())
    assert tensor.shape == (1, 4, 4, 3), f"expected 3 channels, got {tensor.shape}"


def test_decode_image_bytes_raises_on_invalid_data():
    with pytest.raises(Exception):  # PIL raises various exceptions; we just want non-success
        _decode_image_bytes_to_tensor(b"not an image")


def test_decode_image_bytes_returns_torch_tensor():
    """Sanity: output should be a torch.Tensor, not a numpy array."""
    import torch

    data = _png_bytes(2, 2, color=(0, 0, 0))
    tensor = _decode_image_bytes_to_tensor(data)
    assert isinstance(tensor, torch.Tensor)
