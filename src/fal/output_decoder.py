"""Image bytes → ComfyUI IMAGE tensor + URL extraction dispatcher.

Two responsibilities:
  1. Locate the artifact URL inside fal's varied response shapes.
  2. Decode the artifact (image or video) into a ComfyUI tensor.

Video decoding lives in downloads.py (cv2-based); image decoding lives here
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


def _text_from_result(result: dict[str, Any]) -> str:
    """Walk fal LLM/VLM response shapes.

    Recognised shapes (priority order):
      - {response: "..."}                                — most fal LLMs
      - {output: "..."}                                  — some endpoints
      - {text: "..."}                                    — some endpoints
      - {choices: [{message: {content: "..."}}, ...]}    — OpenRouter chat-completions
      - {output: [{content: [{type: "output_text", text: "..."}]}], ...}  — OpenAI Responses API
      - {output_text: "..."}                             — Responses API convenience field
    """
    # Responses API exposes a flat `output_text` convenience field on top of
    # the structured `output` array. Check it first so we don't fall into
    # the older `{output: "<str>"}` branch with mixed shapes.
    output_text = result.get("output_text")
    if isinstance(output_text, str):
        return output_text

    for key in ("response", "output", "text"):
        value = result.get(key)
        if isinstance(value, str):
            return value

    choices = result.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return content

    # OpenAI Responses API: output is a list of items (assistant messages,
    # tool calls, etc.). Find the first message-like item with output_text.
    output = result.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for chunk in content:
                if not isinstance(chunk, dict):
                    continue
                if chunk.get("type") == "output_text":
                    text = chunk.get("text")
                    if isinstance(text, str):
                        return text

    raise RuntimeError(
        f"could not find text response in fal result: keys={list(result.keys())}"
    )


def extract_artifact_url(result: dict[str, Any], kind: str) -> str:
    """Dispatch to the appropriate URL extractor.

    For `kind == "text"`, "URL" is a slight misnomer — text outputs aren't
    downloaded, so we return the response string itself; `decode_artifact`
    then passes it through unchanged.
    """
    if kind == "video":
        return _video_url_from_result(result)
    if kind == "image":
        return _image_url_from_result(result)
    if kind == "text":
        return _text_from_result(result)
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


async def decode_artifact(url: str, kind: str):
    """Async dispatcher: route a URL to the right decoder by output kind.

    For `text`, the value passed in IS the response string (extracted by
    `extract_artifact_url`); we return it unchanged.
    """
    if kind == "video":
        from .downloads import fetch_video_as_frames

        return await fetch_video_as_frames(url)
    if kind == "image":
        return await fetch_image_as_tensor(url)
    if kind == "text":
        return url
    raise NotImplementedError(f"unknown artifact kind: {kind!r}")
