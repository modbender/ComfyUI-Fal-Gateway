"""Issue #16: 429 handling on the fal catalog walk — honour Retry-After, cap
it, and don't sleep after the final attempt."""

from __future__ import annotations

from email.message import Message
from unittest.mock import patch
from urllib import error as urllib_error

from src.fal import _http, catalog as fal_catalog


def _http_error(code: int, retry_after: str | None = None) -> urllib_error.HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib_error.HTTPError("https://api.fal.ai/v1/models", code, "err", headers, None)


def test_retry_delay_uses_default_without_header():
    assert _http.retry_delay_s(_http_error(429), 3.0) == 3.0


def test_retry_delay_honours_larger_retry_after():
    assert _http.retry_delay_s(_http_error(429, "12"), 1.0) == 12.0


def test_retry_delay_caps_retry_after():
    assert _http.retry_delay_s(_http_error(429, "3600"), 1.0) == _http.MAX_RETRY_AFTER_S


def test_retry_delay_ignores_unparseable_retry_after():
    assert _http.retry_delay_s(
        _http_error(429, "Wed, 21 Oct 2026 07:28:00 GMT"), 8.0
    ) == 8.0


def test_429_retries_then_succeeds_using_retry_after():
    page = {"models": [], "has_more": False}
    with patch.object(
        fal_catalog, "_fetch_page", side_effect=[_http_error(429, "5"), page]
    ), patch.object(fal_catalog.time, "sleep") as sleep_mock:
        result = fal_catalog._fetch_page_with_retries(None, None, 10, 1.0, False)

    assert result == page
    sleep_mock.assert_called_once_with(5.0)


def test_429_exhaustion_does_not_sleep_after_final_attempt():
    attempts = len(_http.RETRY_BACKOFF_S) + 1
    with patch.object(
        fal_catalog, "_fetch_page", side_effect=[_http_error(429)] * attempts
    ) as fetch_mock, patch.object(fal_catalog.time, "sleep") as sleep_mock:
        result = fal_catalog._fetch_page_with_retries(None, None, 10, 1.0, False)

    assert result is None
    assert fetch_mock.call_count == attempts
    assert [c.args[0] for c in sleep_mock.call_args_list] == list(_http.RETRY_BACKOFF_S)


def test_non_429_http_error_gives_up_immediately():
    with patch.object(
        fal_catalog, "_fetch_page", side_effect=_http_error(500)
    ) as fetch_mock, patch.object(fal_catalog.time, "sleep") as sleep_mock:
        result = fal_catalog._fetch_page_with_retries(None, None, 10, 1.0, False)

    assert result is None
    assert fetch_mock.call_count == 1
    sleep_mock.assert_not_called()
