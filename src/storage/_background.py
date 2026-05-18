"""Tiny shared helper: kick off a background refresh, dedupe concurrent triggers.

Both the fal catalog and the OpenRouter catalog use stale-while-revalidate:
serve whatever's on disk immediately, then refresh asynchronously so the
caller never blocks on a network roundtrip. This helper is the single
"don't run the same refresh twice in parallel" guard, keyed by task name.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

_log = logging.getLogger("fal_gateway.storage.background")

_lock = threading.Lock()
_in_flight: set[str] = set()


def kick_off(name: str, target: Callable[[], None]) -> bool:
    """Start `target` in a daemon thread under `name`. If a thread with the
    same name is already running, return False without starting another."""
    with _lock:
        if name in _in_flight:
            return False
        _in_flight.add(name)

    def _runner() -> None:
        try:
            target()
        except Exception as exc:  # noqa: BLE001 — best-effort background work
            _log.warning("background task %s failed: %s", name, exc)
        finally:
            with _lock:
                _in_flight.discard(name)

    threading.Thread(target=_runner, name=name, daemon=True).start()
    return True


def is_running(name: str) -> bool:
    with _lock:
        return name in _in_flight
