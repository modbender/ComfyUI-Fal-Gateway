"""Tests for the shared background-task dedupe helper."""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pytest

from src.storage import _background


def _reset() -> None:
    """Ensure clean state between tests — module-level set is shared."""
    with _background._lock:
        _background._in_flight.clear()


def test_kick_off_starts_thread_and_clears_flag_when_done():
    _reset()
    done = threading.Event()

    def target() -> None:
        done.set()

    assert _background.kick_off("task-a", target) is True
    assert done.wait(timeout=2.0)
    # Give the finally-block a moment to clear the flag.
    deadline = time.time() + 1.0
    while _background.is_running("task-a") and time.time() < deadline:
        time.sleep(0.01)
    assert _background.is_running("task-a") is False


def test_kick_off_dedupes_concurrent_triggers():
    """A second kick_off with the same name while the first is in flight
    must return False without starting another thread."""
    _reset()
    started = threading.Event()
    release = threading.Event()

    def target() -> None:
        started.set()
        release.wait(timeout=2.0)

    assert _background.kick_off("task-b", target) is True
    started.wait(timeout=2.0)
    assert _background.kick_off("task-b", target) is False
    release.set()


def test_kick_off_clears_flag_even_when_target_raises():
    _reset()
    raised = threading.Event()

    def target() -> None:
        raised.set()
        raise RuntimeError("simulated failure")

    assert _background.kick_off("task-c", target) is True
    assert raised.wait(timeout=2.0)
    deadline = time.time() + 1.0
    while _background.is_running("task-c") and time.time() < deadline:
        time.sleep(0.01)
    assert _background.is_running("task-c") is False


def test_kick_off_discards_name_when_thread_start_raises():
    """If Thread.start() raises (e.g. thread exhaustion), the name must NOT
    be left wedged in _in_flight — otherwise that refresh is permanently
    disabled until process restart."""
    _reset()

    class _BoomThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    with patch.object(_background.threading, "Thread", _BoomThread):
        with pytest.raises(RuntimeError):
            _background.kick_off("task-d", lambda: None)

    # The name must be gone so a subsequent kick_off can proceed.
    assert _background.is_running("task-d") is False
    # And a real subsequent kick_off with the same name must start.
    done = threading.Event()
    assert _background.kick_off("task-d", done.set) is True
    assert done.wait(timeout=2.0)
