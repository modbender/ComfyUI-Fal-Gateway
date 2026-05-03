"""Fetch pricing data from fal.ai via the `/v1/models/pricing` endpoint.

The pricing endpoint requires authentication and accepts up to 50
endpoint_ids per request. We batch, walk pagination, and bisect on 404
(fal returns 404 for the WHOLE batch when any single id is unknown to its
pricing index).

Single-id 404s land in the `newly_no_pricing` return set so callers can
persist a skip-list and avoid re-requesting known-unknown ids on the next
sweep — see `src/storage/pricing_cache.py`.

Response field aliases (`unit_price` vs `price`, `unit` vs `pricing_unit`)
and envelope variants (`prices` vs `models` vs `data`) are handled by
`PricingPage` in `src/api_models.py` — Pydantic does the alias work
declaratively.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from ..api_models import PricingPage
from ._http import (
    DEFAULT_TIMEOUT_S,
    FAL_API_BASE,
    MAX_PAGES,
    RETRY_BACKOFF_S,
    build_request,
)


_log = logging.getLogger("fal_gateway.pricing")

PRICING_URL = f"{FAL_API_BASE}/models/pricing"
PRICING_BATCH_SIZE = 50  # max endpoint_ids per pricing request
PRICING_INTER_BATCH_SLEEP_S = 0.2  # be polite to the pricing endpoint between batches


def _fetch_pricing_page(
    endpoint_ids: list[str],
    cursor: str | None,
    timeout_s: float,
) -> dict[str, Any]:
    params: dict[str, str] = {"endpoint_id": ",".join(endpoint_ids)}
    if cursor is not None:
        params["cursor"] = cursor
    url = f"{PRICING_URL}?{urllib_parse.urlencode(params)}"
    req = build_request(url)
    with urllib_request.urlopen(req, timeout=timeout_s) as response:
        body = response.read()
    return json.loads(body)


class _PricingFetchOutcome:
    """Result of one pricing-page fetch attempt.

    `page`     — successful response dict (None on failure).
    `status`   — HTTP status code if a response came back at all.
    `terminal` — True if the failure should NOT be retried at the caller level
                 (e.g. 401 unauthorised; bisecting won't help).
    """

    __slots__ = ("page", "status", "terminal")

    def __init__(
        self,
        page: dict[str, Any] | None,
        status: int | None = None,
        terminal: bool = False,
    ):
        self.page = page
        self.status = status
        self.terminal = terminal


def _fetch_pricing_page_with_retries(
    endpoint_ids: list[str],
    cursor: str | None,
    timeout_s: float,
) -> _PricingFetchOutcome:
    """Pricing-aware retry: 429 retries, 404 reports back so the caller can
    bisect to skip an unknown id, 401/403 mark terminal so we stop trying.

    Per-attempt logs use DEBUG so the catalog refresh isn't drowned in noise
    when fal rate-limits or doesn't have pricing for some ids.
    """
    last_err: Exception | None = None
    for attempt, backoff in enumerate((0.0,) + RETRY_BACKOFF_S):
        if backoff > 0:
            time.sleep(backoff)
        try:
            page = _fetch_pricing_page(endpoint_ids, cursor, timeout_s)
            return _PricingFetchOutcome(page=page, status=200)
        except urllib_error.HTTPError as exc:
            last_err = exc
            if exc.code == 429:
                _log.debug("pricing 429 on attempt %d; backing off", attempt + 1)
                continue
            terminal = exc.code in (401, 403)
            return _PricingFetchOutcome(page=None, status=exc.code, terminal=terminal)
        except (urllib_error.URLError, TimeoutError) as exc:
            last_err = exc
            _log.debug("pricing network error on attempt %d: %s", attempt + 1, exc)
            continue
    _log.debug("pricing fetch exhausted retries: %s", last_err)
    return _PricingFetchOutcome(page=None, status=None)


def _absorb_page_into(out: dict[str, dict[str, Any]], page: dict[str, Any]) -> None:
    """Parse one pricing page into `out`, keyed by endpoint_id.

    Pydantic handles the envelope-key variants (`prices` / `models` / `data`)
    and the per-entry alias names (`unit_price` / `price`, `unit` /
    `pricing_unit`). Entries with no endpoint_id are silently skipped.
    """
    parsed = PricingPage.model_validate(page if isinstance(page, dict) else {"prices": page})
    for entry in parsed.prices:
        if not entry.endpoint_id:
            continue
        out[entry.endpoint_id] = {
            "unit_price": entry.unit_price,
            "unit": entry.unit,
            "currency": entry.currency,
        }


def _fetch_pricing_for_batch(
    batch: list[str],
    timeout_s: float,
    out: dict[str, dict[str, Any]],
    no_pricing: set[str],
    counters: dict[str, int],
) -> None:
    """Fetch pricing for one batch, walking pagination and bisecting on 404.

    fal's pricing endpoint returns 404 for the WHOLE batch if any single
    endpoint_id is unknown to the pricing index — so we recursively halve
    until we identify and skip the unknown id. Single-id batches that 404
    add the id to `no_pricing` so subsequent sweeps can skip it via the
    persisted skip-list.
    """
    cursor: str | None = None
    for _page_idx in range(MAX_PAGES):
        outcome = _fetch_pricing_page_with_retries(batch, cursor, timeout_s)
        if outcome.terminal:
            counters["terminal"] += 1
            return
        if outcome.page is None:
            if outcome.status == 404 and len(batch) > 1:
                # Bisect: half the batch must contain the unknown id; the other half
                # is recoverable. Recurse into both halves so we keep at most a single
                # unknown-id loss per batch instead of all 50.
                mid = len(batch) // 2
                _fetch_pricing_for_batch(batch[:mid], timeout_s, out, no_pricing, counters)
                _fetch_pricing_for_batch(batch[mid:], timeout_s, out, no_pricing, counters)
                return
            if outcome.status == 404:
                # Single-id batch confirmed as unknown to the pricing index.
                # Persist it so subsequent sweeps skip the id.
                counters["unknown_ids"] += 1
                if len(batch) == 1:
                    no_pricing.add(batch[0])
            else:
                counters["other_failures"] += 1
            return
        _absorb_page_into(out, outcome.page)
        if not outcome.page.get("has_more"):
            return
        cursor = outcome.page.get("next_cursor")
        if not cursor:
            return


def fetch_all_pricing(
    endpoint_ids: list[str],
    timeout_s: float = DEFAULT_TIMEOUT_S,
    skip_ids: set[str] | None = None,
) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """Batch-fetch pricing for every endpoint_id in `endpoint_ids`.

    Walks the pricing API in batches of `PRICING_BATCH_SIZE`, sleeping briefly
    between batches to ease rate-limit pressure. On 404 (whole-batch failure
    fal returns when any id is unknown) we bisect to recover the recoverable
    half. Single-id 404s are recorded in the returned `newly_no_pricing` set
    so callers can persist them and skip the id on future sweeps.

    Args:
      endpoint_ids: every catalog id to look up.
      skip_ids: optional set of ids to exclude before batching. Pass the
        previously-persisted no-pricing set to cut request count on
        subsequent sweeps.
      timeout_s: per-request timeout.

    Returns:
      `(prices, newly_no_pricing)` where prices maps endpoint_id →
      `{unit_price, unit, currency}`, and newly_no_pricing is the set of
      single-id 404 endpoints discovered during this sweep.
    """
    out: dict[str, dict[str, Any]] = {}
    newly_no_pricing: set[str] = set()
    if not endpoint_ids:
        return out, newly_no_pricing
    skip = skip_ids or set()
    deduped: list[str] = [
        x for x in dict.fromkeys(endpoint_ids) if x not in skip
    ]
    if not deduped:
        return out, newly_no_pricing
    counters = {"unknown_ids": 0, "other_failures": 0, "terminal": 0}
    for start in range(0, len(deduped), PRICING_BATCH_SIZE):
        if start > 0 and PRICING_INTER_BATCH_SLEEP_S > 0:
            time.sleep(PRICING_INTER_BATCH_SLEEP_S)
        batch = deduped[start : start + PRICING_BATCH_SIZE]
        _fetch_pricing_for_batch(batch, timeout_s, out, newly_no_pricing, counters)
        if counters["terminal"]:
            _log.warning(
                "pricing endpoint refused (auth/forbidden) — skipping remaining batches"
            )
            break
    log_fn = _log.warning if (counters["unknown_ids"] or counters["other_failures"]) else _log.info
    log_fn(
        "fetched pricing for %d / %d endpoints (unknown_ids=%d, other_failures=%d, skipped=%d)",
        len(out),
        len(deduped),
        counters["unknown_ids"],
        counters["other_failures"],
        len(skip),
    )
    return out, newly_no_pricing
