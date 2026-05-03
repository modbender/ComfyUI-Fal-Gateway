"""Upload a ComfyUI IMAGE tensor to fal's CDN and return a URL.

Tensor shape: [B, H, W, C] or [H, W, C], float32 in [0, 1].

Uses fal-client's async upload. SHA256-keyed in-process LRU cache (size 32)
dedups identical tensors across sequential nodes in the same workflow run.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import tempfile
from collections import OrderedDict
from typing import Any

import numpy as np
from PIL import Image

import fal_client


_log = logging.getLogger("fal_gateway.uploads")
_CACHE: "OrderedDict[str, str]" = OrderedDict()
_CACHE_MAX = 32


def _tensor_to_pil(tensor: Any) -> Image.Image:
    arr = tensor[0] if hasattr(tensor, "ndim") and tensor.ndim == 4 else tensor
    if hasattr(arr, "cpu"):
        arr = arr.cpu().numpy()
    arr = np.clip(arr * 255.0, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def _pil_sha256(pil: Image.Image) -> str:
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return hashlib.sha256(buf.getvalue()).hexdigest()


def _cache_get(digest: str) -> str | None:
    if digest in _CACHE:
        _CACHE.move_to_end(digest)
        return _CACHE[digest]
    return None


def _cache_put(digest: str, url: str) -> None:
    _CACHE[digest] = url
    _CACHE.move_to_end(digest)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)


async def upload_tensor_image(tensor: Any) -> str:
    """Encode tensor → PNG → fal CDN → return public URL. Dedup identical tensors."""
    pil = await asyncio.to_thread(_tensor_to_pil, tensor)
    digest = await asyncio.to_thread(_pil_sha256, pil)
    cached = _cache_get(digest)
    if cached is not None:
        _log.debug("upload cache hit for %s", digest[:12])
        return cached

    fd, path = tempfile.mkstemp(suffix=".png", prefix="falgw_")
    os.close(fd)
    try:
        await asyncio.to_thread(pil.save, path, "PNG")
        url = await fal_client.upload_file_async(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    _cache_put(digest, url)
    return url
