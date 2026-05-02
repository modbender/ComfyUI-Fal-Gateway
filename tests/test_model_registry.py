"""Tests for `model_registry._entry_from_raw` pricing plumbing.

The catalog and pricing APIs are fetched separately. _entry_from_raw must
fold the pricing dict into the ModelEntry it builds, leaving fields None
when no entry exists for that endpoint_id.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.model_registry import _entry_from_raw


_FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _raw(fixture_name: str) -> dict:
    with open(_FIXTURE_DIR / fixture_name, encoding="utf-8") as f:
        return json.load(f)


def test_entry_from_raw_assigns_pricing_when_provided():
    raw = _raw("fal_ai_flux_dev.json")
    pricing = {
        "fal-ai/flux/dev": {"unit_price": 0.025, "unit": "image", "currency": "USD"}
    }
    entry = _entry_from_raw(raw, pricing=pricing)
    assert entry is not None
    assert entry.id == "fal-ai/flux/dev"
    assert entry.unit_price == 0.025
    assert entry.unit == "image"
    assert entry.currency == "USD"


def test_entry_from_raw_leaves_pricing_none_when_endpoint_missing():
    raw = _raw("fal_ai_flux_dev.json")
    pricing = {"some/other/endpoint": {"unit_price": 0.99}}
    entry = _entry_from_raw(raw, pricing=pricing)
    assert entry is not None
    assert entry.unit_price is None
    assert entry.unit is None
    assert entry.currency is None


def test_entry_from_raw_handles_no_pricing_dict():
    """Older paths that don't supply pricing= should still build an entry."""
    raw = _raw("fal_ai_flux_dev.json")
    entry = _entry_from_raw(raw)
    assert entry is not None
    assert entry.unit_price is None


def test_entry_from_raw_handles_empty_pricing_dict():
    raw = _raw("fal_ai_flux_dev.json")
    entry = _entry_from_raw(raw, pricing={})
    assert entry is not None
    assert entry.unit_price is None
