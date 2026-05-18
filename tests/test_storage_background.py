"""Tests for the shared background-task dedupe helper."""

from __future__ import annotations

import threading
import time

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
