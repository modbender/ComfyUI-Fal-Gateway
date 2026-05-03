"""Download a video URL from fal and decode it into ComfyUI tensors.

Returns:
  - frames: [N, H, W, C] float32 in [0, 1] — what VHS_VideoCombine / SaveVideo expect.
  - audio:  ComfyUI AUDIO dict {"waveform": [1, channels, samples] float32, "sample_rate": int}
            or None if the mp4 has no audio track / ffmpeg is unavailable.

cv2.VideoCapture cannot reliably read from in-memory bytes; we always write a
tempfile. Audio extraction shells out to ffmpeg to dump PCM wav, then parses
with stdlib `wave`. ffmpeg is bundled with ComfyUI (VHS uses it too); if it's
not on PATH we silently return audio=None.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import subprocess
import tempfile
import wave
from typing import Any

import aiohttp
import numpy as np


_log = logging.getLogger("fal_gateway.downloads")
_DOWNLOAD_TIMEOUT_S = 600.0  # 10 min for very long videos
_DOWNLOAD_CHUNK_BYTES = 1 << 20  # 1 MiB
_FFMPEG_TIMEOUT_S = 60.0


async def _download_to_tempfile(url: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".mp4", prefix="falgw_")
    os.close(fd)
    timeout = aiohttp.ClientTimeout(total=_DOWNLOAD_TIMEOUT_S)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                with open(path, "wb") as out:
                    async for chunk in response.content.iter_chunked(_DOWNLOAD_CHUNK_BYTES):
                        out.write(chunk)
    except Exception:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return path


def _decode_to_tensor(path: str) -> Any:
    # Lazy import: cv2 may not be available in dev venvs; only ComfyUI runtime needs it.
    import cv2  # type: ignore[import-not-found]
    import torch  # type: ignore[import-not-found]

    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            raise RuntimeError(f"cv2 could not open downloaded video at {path}")
        frames = []
        while True:
            ok, frame_bgr = cap.read()
            if not ok:
                break
            frames.append(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
    finally:
        cap.release()

    if not frames:
        raise RuntimeError(f"no frames decoded from {path}")

    arr = np.stack(frames, axis=0).astype(np.float32) / 255.0
    return torch.from_numpy(arr)


async def fetch_video_as_frames(url: str) -> Any:
    """Download `url`, decode all frames, return a torch.Tensor of shape [N, H, W, C].

    Kept for backwards-compat with code paths that don't need audio.
    """
    path = await _download_to_tempfile(url)
    try:
        tensor = await asyncio.to_thread(_decode_to_tensor, path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    _log.info("decoded %d frames from %s", tensor.shape[0], url)
    return tensor


async def fetch_video_with_audio(url: str) -> tuple[Any, dict[str, Any] | None]:
    """Download `url`, decode video frames AND extract embedded audio if any.

    Returns (frames_tensor, audio_dict_or_none). Audio is None when the mp4
    has no audio track or ffmpeg is unavailable.
    """
    path = await _download_to_tempfile(url)
    try:
        frames, audio = await asyncio.gather(
            asyncio.to_thread(_decode_to_tensor, path),
            asyncio.to_thread(_extract_audio_or_none, path),
        )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    has_audio = "yes" if audio is not None else "no"
    _log.info(
        "decoded %d frames from %s (audio: %s)",
        frames.shape[0],
        url,
        has_audio,
    )
    return frames, audio


def _extract_audio_or_none(path: str) -> dict[str, Any] | None:
    """Shell out to ffmpeg to extract audio as PCM s16le wav. Returns None on any failure."""
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-i",
                path,
                "-vn",  # no video
                "-acodec",
                "pcm_s16le",
                "-f",
                "wav",
                "-",
            ],
            capture_output=True,
            timeout=_FFMPEG_TIMEOUT_S,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        _log.debug("ffmpeg unavailable or timed out: %s", exc)
        return None
    if result.returncode != 0 or not result.stdout:
        _log.debug("ffmpeg returned no audio (rc=%s)", result.returncode)
        return None
    return _decode_wav_bytes(result.stdout)


def _decode_wav_bytes(wav_data: bytes) -> dict[str, Any] | None:
    """PCM s16le wav bytes → ComfyUI AUDIO dict, or None on error/empty."""
    import torch  # type: ignore[import-not-found]

    if not wav_data:
        return None
    try:
        with wave.open(io.BytesIO(wav_data), "rb") as wf:
            n_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            sample_rate = wf.getframerate()
            n_frames = wf.getnframes()
            raw = wf.readframes(n_frames)
    except (wave.Error, EOFError):
        return None

    if n_frames == 0 or not raw:
        return None

    if sample_width == 2:
        arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 1:
        arr = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sample_width == 4:
        arr = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        return None

    if n_channels > 1:
        arr = arr.reshape(-1, n_channels).T.copy()  # [channels, samples]
    else:
        arr = arr[np.newaxis, :].copy()

    waveform = torch.from_numpy(arr).unsqueeze(0)  # [1, channels, samples]
    return {"waveform": waveform, "sample_rate": sample_rate}
