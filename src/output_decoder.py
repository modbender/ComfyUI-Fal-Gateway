"""Image bytes → ComfyUI IMAGE tensor + URL extraction dispatcher.

Two responsibilities:
  1. Locate the artifact URL inside fal's varied response shapes.
  2. Decode the artifact (image or video) into a ComfyUI tensor.

Video decoding lives in fal_downloads.py (cv2-based); image decoding lives here
(PIL-based). The dispatcher `decode_artifact(url, kind)` routes to the right one.
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Any

import aiohttp
import numpy as np
from PIL import Image


_log = logging.getLogger("fal_gateway.output_decoder")
_DOWNLOAD_TIMEOUT_S = 120.0


def _video_url_from_result(result: dict[str, Any]) -> str:
    """Walk fal video response shapes. Mirrors the original helper from base.py."""
    video = result.get("video")
    if isinstance(video, dict):
        url = video.get("url")
        if url:
            return str(url)
    if isinstance(result.get("url"), str):
        return str(result["url"])
    raise RuntimeError(
        f"could not find video URL in fal result: keys={list(result.keys())}"
    )


def _image_url_from_result(result: dict[str, Any]) -> str:
    """Walk fal image response shapes.

    Recognised shapes (in priority order):
      - {images: [{url, ...}, ...]} — most fal image models
      - {image: {url, ...}}          — legacy single-image
      - {output: {url, ...}}          — some endpoints
      - {output: [{url, ...}, ...]}   — output-as-array variant
      - {url: ...}                    — bare top-level URL
    """
    images = result.get("images")
    if isinstance(images, list):
        for entry in images:
            if isinstance(entry, dict):
                url = entry.get("url")
                if url:
                    return str(url)

    image = result.get("image")
    if isinstance(image, dict):
        url = image.get("url")
        if url:
            return str(url)

    output = result.get("output")
    if isinstance(output, dict):
        url = output.get("url")
        if url:
            return str(url)
    if isinstance(output, list):
        for entry in output:
            if isinstance(entry, dict):
                url = entry.get("url")
                if url:
                    return str(url)

    if isinstance(result.get("url"), str):
        return str(result["url"])

    raise RuntimeError(
        f"could not find image URL in fal result: keys={list(result.keys())}"
    )


def extract_artifact_url(result: dict[str, Any], kind: str) -> str:
    """Dispatch to the appropriate URL extractor."""
    if kind == "video":
        return _video_url_from_result(result)
    if kind == "image":
        return _image_url_from_result(result)
    raise NotImplementedError(f"unknown artifact kind: {kind!r}")


def _decode_image_bytes_to_tensor(data: bytes) -> "torch.Tensor":
    """Decode raw image bytes (PNG / JPEG / WebP / etc.) to a ComfyUI IMAGE tensor.

    Output shape: [1, H, W, 3] float32 in [0, 1].

    Mode handling:
      - RGBA → RGB (alpha dropped). v2.x may surface alpha later as a MASK output.
      - Grayscale (L, LA) → RGB (channel duplicated).
      - Anything else → forced through `img.convert("RGB")`.
    """
    import torch  # type: ignore[import-not-found]

    img = Image.open(io.BytesIO(data))
    img.load()
    if img.mode != "RGB":
        img = img.convert("RGB")
    arr = np.asarray(img, dtype=np.float32) / 255.0
    return torch.from_numpy(arr).unsqueeze(0)


async def fetch_image_as_tensor(url: str) -> "torch.Tensor":
    """Download an image URL and decode to ComfyUI tensor [1,H,W,3] in [0,1]."""
    timeout = aiohttp.ClientTimeout(total=_DOWNLOAD_TIMEOUT_S)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as response:
            response.raise_for_status()
            data = await response.read()
    tensor = await asyncio.to_thread(_decode_image_bytes_to_tensor, data)
    _log.info("decoded image %dx%d from %s", tensor.shape[2], tensor.shape[1], url)
    return tensor


async def decode_artifact(url: str, kind: str) -> "torch.Tensor":
    """Async dispatcher: route a URL to the right decoder by output kind."""
    if kind == "video":
        from .fal_downloads import fetch_video_as_frames

        return await fetch_video_as_frames(url)
    if kind == "image":
        return await fetch_image_as_tensor(url)
    raise NotImplementedError(f"unknown artifact kind: {kind!r}")
