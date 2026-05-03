"""Tests for the WAV decoder used to extract embedded audio from downloaded mp4s.

The mp4-extraction path itself uses ffmpeg subprocess and is exercised in the
integration suite. Here we cover the pure WAV-bytes → ComfyUI AUDIO dict
conversion that runs after ffmpeg.
"""

from __future__ import annotations

import io
import struct
import wave

import torch

from src.fal.downloads import _decode_wav_bytes


def _build_wav_bytes(
    samples: list[tuple[int, ...]],
    n_channels: int = 1,
    sample_rate: int = 44100,
    sample_width: int = 2,
) -> bytes:
    """Create wav bytes from int16 sample tuples."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(n_channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        fmt = "<" + ("h" * n_channels)
        for sample in samples:
            wf.writeframes(struct.pack(fmt, *sample))
    return buf.getvalue()


def test_decode_wav_bytes_mono_pcm16():
    samples = [(0,), (16384,), (-16384,), (0,)]
    data = _build_wav_bytes(samples, n_channels=1, sample_rate=22050)
    out = _decode_wav_bytes(data)
    assert out is not None
    assert out["sample_rate"] == 22050
    waveform = out["waveform"]
    # ComfyUI AUDIO shape: [batch, channels, samples]
    assert waveform.shape == (1, 1, 4)
    assert waveform.dtype == torch.float32
    # 16384 / 32768 ≈ 0.5
    assert abs(waveform[0, 0, 1].item() - 0.5) < 0.001


def test_decode_wav_bytes_stereo_pcm16_keeps_channels_separate():
    samples = [(100, 200), (300, 400), (500, 600)]
    data = _build_wav_bytes(samples, n_channels=2, sample_rate=48000)
    out = _decode_wav_bytes(data)
    assert out is not None
    assert out["sample_rate"] == 48000
    waveform = out["waveform"]
    assert waveform.shape == (1, 2, 3)
    # Channel 0: [100, 300, 500] / 32768
    assert abs(waveform[0, 0, 0].item() - 100 / 32768) < 1e-5
    assert abs(waveform[0, 1, 1].item() - 400 / 32768) < 1e-5


def test_decode_wav_bytes_returns_none_on_empty_data():
    assert _decode_wav_bytes(b"") is None


def test_decode_wav_bytes_returns_none_on_invalid_bytes():
    assert _decode_wav_bytes(b"this is not a wav file") is None


def test_decode_wav_bytes_returns_none_on_zero_frames():
    """A wav header with no audio frames should return None (no usable audio)."""
    data = _build_wav_bytes([], n_channels=1, sample_rate=44100)
    assert _decode_wav_bytes(data) is None


def test_decode_wav_bytes_sample_rate_preserved():
    for rate in (8000, 16000, 22050, 44100, 48000):
        data = _build_wav_bytes([(0,), (1000,)], sample_rate=rate)
        out = _decode_wav_bytes(data)
        assert out is not None
        assert out["sample_rate"] == rate
