"""Tests for `src.fal.pricing.fetch_all_pricing`.

The pricing API takes up to PRICING_BATCH_SIZE endpoint_ids per call,
authenticates via FAL_KEY, and may paginate via next_cursor. We mock
`urlopen` so these tests run offline and deterministically.
"""

from __future__ import annotations

import io
import json
from unittest.mock import patch
from urllib import error as urllib_error

import pytest

from src.fal.pricing import PRICING_BATCH_SIZE, fetch_all_pricing


# ---- helpers ----------------------------------------------------------


class _FakeResponse:
    def __init__(self, body: dict | list | str):
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        self._buf = io.BytesIO(body.encode("utf-8"))

    def read(self):
        return self._buf.read()

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        self._buf.close()
        return False


def _make_urlopen(pages: list):
    """Build a fake urlopen that returns each entry from `pages` in order."""
    iterator = iter(pages)

    def _fake_urlopen(req, timeout=None):
        next_page = next(iterator)
        if isinstance(next_page, Exception):
            raise next_page
        return _FakeResponse(next_page)

    return _fake_urlopen


def _capture_urlopen(captured_urls: list, response_factory):
    def _fake_urlopen(req, timeout=None):
        captured_urls.append(req.full_url)
        return _FakeResponse(response_factory(req.full_url))

    return _fake_urlopen


# ---- batching ----------------------------------------------------------


def test_batches_to_50_ids_per_request():
    ids = [f"fal-ai/m{i}" for i in range(120)]
    captured = []

    def respond(url):
        return {"prices": []}

    with patch("src.fal.pricing.urllib_request.urlopen", _capture_urlopen(captured, respond)):
        fetch_all_pricing(ids)

    # 120 / 50 = 3 batches
    assert len(captured) == 3
    assert PRICING_BATCH_SIZE == 50
    # Each request should carry up to 50 ids.
    for i, url in enumerate(captured):
        ids_param = url.split("endpoint_id=", 1)[1].split("&", 1)[0]
        # urlencode quotes commas, so split on the encoded delimiter
        count = ids_param.count("%2C") + 1 if ids_param else 0
        expected = 50 if i < 2 else 20
        assert count == expected, f"batch {i} had {count} ids, expected {expected}"


def test_walks_paginated_cursor_within_batch():
    pages = [
        {
            "prices": [
                {"endpoint_id": "fal-ai/a", "unit_price": 0.01, "unit": "image", "currency": "USD"}
            ],
            "has_more": True,
            "next_cursor": "cursor-2",
        },
        {
            "prices": [
                {"endpoint_id": "fal-ai/b", "unit_price": 0.02, "unit": "image", "currency": "USD"}
            ],
            "has_more": False,
            "next_cursor": None,
        },
    ]
    with patch("src.fal.pricing.urllib_request.urlopen", _make_urlopen(pages)):
        out, _ = fetch_all_pricing(["fal-ai/a", "fal-ai/b"])
    assert "fal-ai/a" in out and "fal-ai/b" in out
    assert out["fal-ai/a"]["unit_price"] == 0.01
    assert out["fal-ai/b"]["unit_price"] == 0.02


def test_returns_dict_keyed_by_endpoint_id():
    page = {
        "prices": [
            {"endpoint_id": "fal-ai/flux/dev", "unit_price": 0.025, "unit": "image", "currency": "USD"},
            {"endpoint_id": "bytedance/seedance", "unit_price": 0.30, "unit": "second", "currency": "USD"},
        ],
        "has_more": False,
    }
    with patch("src.fal.pricing.urllib_request.urlopen", _make_urlopen([page])):
        out, _ = fetch_all_pricing(["fal-ai/flux/dev", "bytedance/seedance"])
    assert out["fal-ai/flux/dev"] == {"unit_price": 0.025, "unit": "image", "currency": "USD"}
    assert out["bytedance/seedance"] == {"unit_price": 0.30, "unit": "second", "currency": "USD"}


def test_omits_endpoints_without_pricing():
    """fal may return prices for a subset of requested ids; missing ones must
    not appear in the returned dict so callers can detect via .get()."""
    page = {"prices": [{"endpoint_id": "fal-ai/a", "unit_price": 0.01, "unit": "image"}]}
    with patch("src.fal.pricing.urllib_request.urlopen", _make_urlopen([page])):
        out, _ = fetch_all_pricing(["fal-ai/a", "fal-ai/no-price"])
    assert "fal-ai/a" in out
    assert "fal-ai/no-price" not in out


def test_handles_401_returns_empty_dict():
    """Missing/invalid FAL_KEY → 401. We log + degrade gracefully, not crash."""
    err = urllib_error.HTTPError(
        url="x", code=401, msg="Unauthorized", hdrs=None, fp=io.BytesIO(b"")
    )
    with patch("src.fal.pricing.urllib_request.urlopen", _make_urlopen([err])):
        out, _ = fetch_all_pricing(["fal-ai/a"])
    assert out == {}


def test_handles_429_via_retry_with_backoff():
    """First attempt 429s, retry succeeds — final dict should reflect successful page."""
    err = urllib_error.HTTPError(
        url="x", code=429, msg="Too Many Requests", hdrs=None, fp=io.BytesIO(b"")
    )
    success = {"prices": [{"endpoint_id": "fal-ai/a", "unit_price": 0.01, "unit": "image"}]}
    with patch("src.fal.pricing.urllib_request.urlopen", _make_urlopen([err, success])):
        with patch("src.fal.pricing.time.sleep") as mock_sleep:  # avoid real backoff in tests
            out, _ = fetch_all_pricing(["fal-ai/a"])
    assert out["fal-ai/a"]["unit_price"] == 0.01
    assert mock_sleep.called  # backoff was invoked


def test_empty_input_returns_empty_dict():
    """No endpoint_ids → no requests, empty dict."""
    captured = []

    def respond(url):
        return {}

    with patch(
        "src.fal.pricing.urllib_request.urlopen", _capture_urlopen(captured, respond)
    ):
        out, _ = fetch_all_pricing([])
    assert out == {}
    assert captured == []  # no HTTP calls


def test_dedupes_repeated_endpoint_ids():
    """If the caller passes the same id twice, we should only request it once."""
    captured = []

    def respond(url):
        return {"prices": []}

    with patch("src.fal.pricing.urllib_request.urlopen", _capture_urlopen(captured, respond)):
        fetch_all_pricing(["fal-ai/a", "fal-ai/a", "fal-ai/a"])
    assert len(captured) == 1
    ids_param = captured[0].split("endpoint_id=", 1)[1].split("&", 1)[0]
    # urlencode produces "fal-ai%2Fa" once
    assert ids_param.count("fal-ai") == 1


def test_tolerates_alternate_envelope_keys():
    """Some endpoints may wrap in `models` instead of `prices`. Both should work."""
    page = {"models": [{"endpoint_id": "fal-ai/a", "unit_price": 0.07, "unit": "second"}]}
    with patch("src.fal.pricing.urllib_request.urlopen", _make_urlopen([page])):
        out, _ = fetch_all_pricing(["fal-ai/a"])
    assert out["fal-ai/a"]["unit_price"] == 0.07


def test_normalizes_alt_field_names():
    """`price` (no _unit) and `pricing_unit` should be accepted as aliases."""
    page = {
        "prices": [
            {"endpoint_id": "fal-ai/a", "price": 0.15, "pricing_unit": "megapixel"}
        ]
    }
    with patch("src.fal.pricing.urllib_request.urlopen", _make_urlopen([page])):
        out, _ = fetch_all_pricing(["fal-ai/a"])
    assert out["fal-ai/a"]["unit_price"] == 0.15
    assert out["fal-ai/a"]["unit"] == "megapixel"


def test_currency_defaults_to_usd_when_missing():
    page = {"prices": [{"endpoint_id": "fal-ai/a", "unit_price": 0.01, "unit": "image"}]}
    with patch("src.fal.pricing.urllib_request.urlopen", _make_urlopen([page])):
        out, _ = fetch_all_pricing(["fal-ai/a"])
    assert out["fal-ai/a"]["currency"] == "USD"


# ---- 404 handling: fal returns 404 for the whole batch when any id is unknown ----


def _http_404():
    return urllib_error.HTTPError(
        url="x", code=404, msg="Not Found", hdrs=None, fp=io.BytesIO(b"")
    )


def test_404_on_full_batch_bisects_to_recover_known_ids():
    """fal returns 404 for the entire batch when one id is unknown. We halve
    until the unknown id is isolated, recovering pricing for the rest.
    Two-id batch: first call 404s, second call (left half = id A) succeeds,
    third call (right half = id B unknown) 404s.
    """
    err = _http_404()
    success_a = {"prices": [{"endpoint_id": "fal-ai/a", "unit_price": 0.01, "unit": "image"}]}
    err2 = _http_404()
    with patch(
        "src.fal.pricing.urllib_request.urlopen", _make_urlopen([err, success_a, err2])
    ):
        with patch("src.fal.pricing.time.sleep"):  # skip throttle in test
            out, _ = fetch_all_pricing(["fal-ai/a", "fal-ai/unknown"])
    assert "fal-ai/a" in out
    assert "fal-ai/unknown" not in out


def test_404_on_single_id_does_not_recurse_infinitely():
    """A 1-id batch that 404s must be skipped (no further bisection)."""
    with patch("src.fal.pricing.urllib_request.urlopen", _make_urlopen([_http_404()])):
        with patch("src.fal.pricing.time.sleep"):
            out, _ = fetch_all_pricing(["fal-ai/unknown"])
    assert out == {}


def test_single_id_404_adds_to_newly_no_pricing():
    """Confirmed-unknown single id must surface in the newly_no_pricing set
    so callers can persist a skip-list."""
    with patch("src.fal.pricing.urllib_request.urlopen", _make_urlopen([_http_404()])):
        with patch("src.fal.pricing.time.sleep"):
            out, no_pricing = fetch_all_pricing(["fal-ai/unknown"])
    assert out == {}
    assert no_pricing == {"fal-ai/unknown"}


def test_skip_ids_excludes_them_from_request_batches():
    """When skip_ids is passed, those ids must not appear in any HTTP request."""
    captured = []

    def respond(url):
        return {"prices": []}

    with patch(
        "src.fal.pricing.urllib_request.urlopen", _capture_urlopen(captured, respond)
    ):
        out, no_pricing = fetch_all_pricing(
            ["fal-ai/a", "fal-ai/b", "fal-ai/skip-me"],
            skip_ids={"fal-ai/skip-me"},
        )
    assert out == {}
    assert no_pricing == set()
    # Only one HTTP request, with the two non-skipped ids.
    assert len(captured) == 1
    ids_param = captured[0].split("endpoint_id=", 1)[1].split("&", 1)[0]
    assert "skip-me" not in ids_param
    assert "fal-ai" in ids_param


def test_skip_ids_eliminates_request_when_all_filtered():
    """If every id is in skip_ids, no HTTP request should fire."""
    captured = []

    def respond(url):
        return {"prices": []}

    with patch(
        "src.fal.pricing.urllib_request.urlopen", _capture_urlopen(captured, respond)
    ):
        out, no_pricing = fetch_all_pricing(
            ["fal-ai/a", "fal-ai/b"],
            skip_ids={"fal-ai/a", "fal-ai/b"},
        )
    assert out == {}
    assert no_pricing == set()
    assert captured == []


def test_403_treated_as_terminal_breaks_remaining_batches():
    """403 means future batches will also fail — stop early instead of looping."""
    err = urllib_error.HTTPError(
        url="x", code=403, msg="Forbidden", hdrs=None, fp=io.BytesIO(b"")
    )
    captured = []

    def respond_or_403(url):
        if not captured:
            captured.append(url)
            raise err
        captured.append(url)
        return {"prices": []}

    def _fake_urlopen(req, timeout=None):
        return _FakeResponse(respond_or_403(req.full_url))

    # Build many batches' worth of ids; only the first should be attempted.
    ids = [f"fal-ai/m{i}" for i in range(120)]

    def _stop_after_first_403(req, timeout=None):
        url = req.full_url
        captured.append(url)
        raise err  # always 403

    with patch("src.fal.pricing.urllib_request.urlopen", _stop_after_first_403):
        with patch("src.fal.pricing.time.sleep"):
            out, _ = fetch_all_pricing(ids)
    assert out == {}
    # 3 batches × 4 retry attempts = 12 max if we kept going. Terminal short-
    # circuit caps the requests at exactly 1 (the first batch only, no retries
    # because terminal short-circuits the retry loop too).
    assert len(captured) == 1, f"403 should stop after first call, got {len(captured)}"
