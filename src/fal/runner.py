"""Wrapper around fal-client's async submit/poll loop.

Centralises error logging, cancellation, the queue-wait timeout, and per-call
AsyncClient instantiation to avoid the "every-other-call event-loop-closed" bug
that hits when fal_client's module-level singleton AsyncClient re-uses a
connection pool whose transports were bound to a dead ComfyUI event loop.

Each `run_async` call gets its own fresh `fal_client.AsyncClient()`, which
lazily creates its `httpx.AsyncClient` on first use *in the current loop*; we
close that httpx pool explicitly in `finally`.

We submit + poll manually (rather than `subscribe()`) so we can bound the queue
wait. When fal accepts a job but never assigns a runner — e.g. the account is
out of credits — the job sits `IN_QUEUE` forever and `subscribe()` polls
forever, freezing ComfyUI. The server-side `X-Fal-Request-Timeout` header does
not help: fal only honours that deadline once a runner picks the job up. So the
bound must be client-side, and it must apply to the QUEUE WAIT ONLY — never to
total time — or long video renders that are actively processing would be killed.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Awaitable, Callable

import fal_client
from fal_client import Completed, InProgress, Queued


_log = logging.getLogger("fal_gateway.runner")

ProgressCallback = Callable[[Any], Awaitable[None] | None]

# Bounds the time a job may sit IN_QUEUE before a runner picks it up. Once
# processing starts this no longer applies, so long renders are unaffected.
QUEUE_TIMEOUT_S = float(os.environ.get("FAL_GATEWAY_QUEUE_TIMEOUT_S", "120"))
POLL_INTERVAL_S = float(os.environ.get("FAL_GATEWAY_POLL_INTERVAL_S", "1.0"))


async def run_async(
    model_id: str,
    payload: dict[str, Any],
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Submit a fal job and wait for the final result.

    `on_progress` receives raw fal status updates (Queued, InProgress, Completed)
    so callers can forward to ComfyUI's progress channel if desired.
    """
    # Retain spawned progress-callback tasks so they aren't GC'd mid-flight.
    progress_tasks: set[asyncio.Task[Any]] = set()

    def _forward_progress(status: Any) -> None:
        if on_progress is None:
            return
        try:
            result = on_progress(status)
            if asyncio.iscoroutine(result):
                # Schedule on the running loop without blocking the poll loop.
                task = asyncio.get_running_loop().create_task(result)
                progress_tasks.add(task)
                task.add_done_callback(progress_tasks.discard)
        except Exception:  # noqa: BLE001 — never let progress callbacks kill the run
            _log.exception("on_progress callback raised; ignoring")

    # Fresh AsyncClient per call — its lazy httpx pool is bound to THIS event
    # loop. Avoids the singleton's stale-connection crash on Windows where
    # ComfyUI's per-prompt loop teardown leaves the pool's transports tied to a
    # closed loop, then the next call's connection-recycle path explodes with
    # `RuntimeError: Event loop is closed`.
    client = fal_client.AsyncClient()
    handle = None
    try:
        handle = await client.submit(model_id, arguments=payload)
        loop = asyncio.get_running_loop()
        start = loop.time()
        started = False

        while True:
            status = await handle.status(with_logs=True)
            _forward_progress(status)

            if isinstance(status, Completed):
                if status.error:
                    raise RuntimeError(f"fal job failed: {status.error}")
                break
            elif isinstance(status, InProgress):
                started = True
            elif isinstance(status, Queued):
                if not started and loop.time() - start > QUEUE_TIMEOUT_S:
                    # cancel() is unreliable on zero-credit queued jobs (may 400
                    # ALREADY_COMPLETED); best-effort, never let it mask this error.
                    try:
                        await handle.cancel()
                    except Exception:  # noqa: BLE001 — cancel is best-effort
                        pass
                    raise RuntimeError(
                        f"fal job for {model_id} stayed IN_QUEUE for over "
                        f"{QUEUE_TIMEOUT_S:.0f}s without a runner. Likely causes: "
                        "fal account out of credits, or no runner available for "
                        "this model. Raise FAL_GATEWAY_QUEUE_TIMEOUT_S to wait longer."
                    )

            await asyncio.sleep(POLL_INTERVAL_S)

        return await handle.get()
    except asyncio.CancelledError:
        # ComfyUI interrupt: best-effort cancel so the remote job stops billing.
        if handle is not None:
            try:
                await handle.cancel()
            except Exception:  # noqa: BLE001 — cancel is best-effort
                pass
        _log.info("fal job for %s cancelled", model_id)
        raise
    except Exception as exc:
        _log.error("fal job for %s failed: %s", model_id, exc)
        raise
    finally:
        # Best-effort cleanup of the lazily-built httpx pool. AsyncClient is a
        # frozen dataclass; its `_client` cached_property stores an
        # asyncstdlib AwaitableValue, not the httpx client directly — awaiting
        # the AwaitableValue yields the real httpx.AsyncClient to close.
        awaitable_value = client.__dict__.get("_client")
        if awaitable_value is not None:
            try:
                httpx_client = await awaitable_value
                await httpx_client.aclose()
            except Exception:  # noqa: BLE001 — cleanup is best-effort
                pass
