"""Unit tests for `src.fal.runner.run_async`.

All tests run fully offline: `fal_client.AsyncClient` is monkeypatched with a
fake whose handle returns a scripted sequence of real `fal_client` Status
instances. The queue-wait timeout and poll interval are shrunk to tiny values
so the timeout path resolves in milliseconds.

The central invariant under test: the queue-wait timeout bounds ONLY the time a
job spends `IN_QUEUE` before a runner picks it up. Once processing starts
(`InProgress`), elapsed time is irrelevant — long renders must never be killed.
"""

from __future__ import annotations

import asyncio

import pytest
from fal_client import Completed, InProgress, Queued

from src.fal import runner


_SENTINEL_RESULT = {"images": [{"url": "https://example.invalid/out.png"}]}


class _FakeHandle:
    """Returns scripted Status objects from `status()`; records cancel calls."""

    def __init__(self, statuses, result=None):
        self._statuses = list(statuses)
        self._result = _SENTINEL_RESULT if result is None else result
        self._idx = 0
        self.cancel_calls = 0

    async def status(self, with_logs: bool = False):
        # Hold on the last status once the script is exhausted (e.g. always-Queued).
        if self._idx < len(self._statuses):
            status = self._statuses[self._idx]
            self._idx += 1
        else:
            status = self._statuses[-1]
        return status

    async def get(self):
        return self._result

    async def cancel(self):
        self.cancel_calls += 1


class _FakeAwaitableValue:
    """Mimics asyncstdlib's AwaitableValue: awaiting it yields the wrapped client."""

    def __init__(self, value):
        self._value = value

    def __await__(self):
        async def _coro():
            return self._value

        return _coro().__await__()


class _FakeHttpxClient:
    def __init__(self):
        self.aclose_calls = 0

    async def aclose(self):
        self.aclose_calls += 1


class _FakeAsyncClient:
    """Stand-in for `fal_client.AsyncClient`.

    Exposes `__dict__["_client"]` as an AwaitableValue wrapping a fake httpx
    client, matching the real cached_property shape the cleanup code unwraps.
    """

    def __init__(self, handle):
        self._handle = handle
        self.submit_calls = 0
        self.httpx = _FakeHttpxClient()
        self.__dict__["_client"] = _FakeAwaitableValue(self.httpx)

    async def submit(self, application, arguments=None, **kwargs):
        self.submit_calls += 1
        return self._handle


@pytest.fixture
def _fast_timeouts(monkeypatch):
    monkeypatch.setattr(runner, "QUEUE_TIMEOUT_S", 0.05)
    monkeypatch.setattr(runner, "POLL_INTERVAL_S", 0.001)


def _install_client(monkeypatch, handle) -> _FakeAsyncClient:
    fake = _FakeAsyncClient(handle)
    monkeypatch.setattr(runner.fal_client, "AsyncClient", lambda *a, **k: fake)
    return fake


async def test_queue_timeout_raises_and_attempts_cancel(monkeypatch, _fast_timeouts):
    handle = _FakeHandle([Queued(position=0)])  # never leaves the queue
    _install_client(monkeypatch, handle)

    with pytest.raises(RuntimeError) as excinfo:
        await runner.run_async("some/model", {"prompt": "x"})

    msg = str(excinfo.value).lower()
    assert "queue" in msg or "credit" in msg
    assert handle.cancel_calls >= 1


async def test_processing_past_deadline_does_not_timeout(monkeypatch, _fast_timeouts):
    # Two queued polls, then plenty of InProgress to push elapsed past
    # QUEUE_TIMEOUT_S, then Completed. The timeout must NOT fire.
    statuses = (
        [Queued(position=1), Queued(position=0)]
        + [InProgress(logs=[]) for _ in range(80)]
        + [Completed(logs=[], metrics={}, error=None)]
    )
    handle = _FakeHandle(statuses, result=_SENTINEL_RESULT)
    _install_client(monkeypatch, handle)

    result = await runner.run_async("some/model", {"prompt": "x"})

    assert result is _SENTINEL_RESULT
    assert handle.cancel_calls == 0


async def test_completed_with_error_raises(monkeypatch, _fast_timeouts):
    handle = _FakeHandle(
        [InProgress(logs=[]), Completed(logs=[], metrics={}, error="boom")]
    )
    _install_client(monkeypatch, handle)

    with pytest.raises(RuntimeError) as excinfo:
        await runner.run_async("some/model", {"prompt": "x"})

    assert "boom" in str(excinfo.value)


async def test_progress_callback_invoked_per_update(monkeypatch, _fast_timeouts):
    statuses = [
        Queued(position=0),
        InProgress(logs=[]),
        Completed(logs=[], metrics={}, error=None),
    ]
    handle = _FakeHandle(statuses)
    _install_client(monkeypatch, handle)

    calls: list[object] = []

    def on_progress(update):
        calls.append(update)

    result = await runner.run_async("some/model", {"prompt": "x"}, on_progress)

    assert result is _SENTINEL_RESULT
    assert len(calls) == 3


async def test_httpx_client_closed_in_finally(monkeypatch, _fast_timeouts):
    handle = _FakeHandle(
        [InProgress(logs=[]), Completed(logs=[], metrics={}, error=None)]
    )
    fake = _install_client(monkeypatch, handle)

    await runner.run_async("some/model", {"prompt": "x"})

    assert fake.httpx.aclose_calls == 1


async def test_cancelled_error_cancels_remote_and_reraises(monkeypatch, _fast_timeouts):
    class _CancellingHandle(_FakeHandle):
        async def status(self, with_logs: bool = False):
            raise asyncio.CancelledError

    handle = _CancellingHandle([Queued(position=0)])
    _install_client(monkeypatch, handle)

    with pytest.raises(asyncio.CancelledError):
        await runner.run_async("some/model", {"prompt": "x"})

    assert handle.cancel_calls >= 1
