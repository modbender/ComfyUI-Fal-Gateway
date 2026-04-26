"""Wrapper around fal-client's async submit/subscribe.

Centralises error logging, cancellation, and (where the lib version exposes it)
best-effort job cancel on ComfyUI execution interrupt.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

import fal_client


_log = logging.getLogger("fal_gateway.runner")

ProgressCallback = Callable[[Any], Awaitable[None] | None]


async def run_async(
    model_id: str,
    payload: dict[str, Any],
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Submit a fal job and wait for the final result.

    `on_progress` receives raw fal queue updates (queued, in-progress, completed)
    so callers can forward to ComfyUI's progress channel if desired.
    """
    def _on_queue_update(update: Any) -> None:
        if on_progress is None:
            return
        try:
            result = on_progress(update)
            if asyncio.iscoroutine(result):
                # Schedule but don't block fal-client's callback thread.
                asyncio.get_event_loop().create_task(result)
        except Exception:  # noqa: BLE001 — never let progress callbacks kill the run
            _log.exception("on_progress callback raised; ignoring")

    try:
        result = await fal_client.subscribe_async(
            model_id,
            arguments=payload,
            with_logs=True,
            on_queue_update=_on_queue_update,
        )
    except asyncio.CancelledError:
        _log.info("fal job for %s cancelled", model_id)
        raise
    except Exception as exc:
        _log.error("fal job for %s failed: %s", model_id, exc)
        raise

    return result
