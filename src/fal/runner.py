"""Wrapper around fal-client's async submit/subscribe.

Centralises error logging, cancellation, and per-call AsyncClient
instantiation to avoid the "every-other-call event-loop-closed" bug
that hits when fal_client's module-level singleton AsyncClient
re-uses a connection pool whose transports were bound to a dead
ComfyUI event loop.

Each `run_async` call gets its own fresh `fal_client.AsyncClient()`,
which lazily creates its `httpx.AsyncClient` on first use *in the
current loop*. The client is GC'd at function exit; httpx warnings
about unclosed clients are quieter than crashes.
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

    # Fresh AsyncClient per call — its lazy httpx pool is bound to THIS
    # event loop. Avoids the singleton's stale-connection crash on Windows
    # where ComfyUI's per-prompt loop teardown leaves the pool's transports
    # tied to a closed loop, then the next call's connection-recycle path
    # explodes with `RuntimeError: Event loop is closed`.
    client = fal_client.AsyncClient()
    try:
        result = await client.subscribe(
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
    finally:
        # Best-effort cleanup of the lazily-built httpx pool. AsyncClient is
        # a frozen dataclass without an `aclose()` method, but its `_client`
        # cached_property holds the httpx.AsyncClient we want to close.
        httpx_client = client.__dict__.get("_client")
        if httpx_client is not None:
            try:
                await httpx_client.aclose()
            except Exception:  # noqa: BLE001 — cleanup is best-effort
                pass

    return result
