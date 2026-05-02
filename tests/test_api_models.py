"""Tests for src/api_models.py — Pydantic boundary models.

We test the shapes that protect against external variability:
  - Field aliases (PriceEntry: `unit_price` vs `price`, `unit` vs `pricing_unit`)
  - Envelope aliases (PricingPage: `prices` vs `models` vs `data`)
  - Cache file load/save round-trip
  - HTTP response shape stability
"""

from __future__ import annotations

import json

import pytest

from src.api_models import (
    CatalogCacheFile,
    ErrorResponse,
    HealthResponse,
    PriceEntry,
    PricingCacheFile,
    PricingPage,
    PricingRefreshResponse,
    RefreshResponse,
    SchemaResponse,
)


# ---- PriceEntry: alias handling ---------------------------------------


def test_price_entry_canonical_keys():
    entry = PriceEntry.model_validate(
        {"endpoint_id": "fal-ai/flux/dev", "unit_price": 0.025, "unit": "image", "currency": "USD"}
    )
    assert entry.endpoint_id == "fal-ai/flux/dev"
    assert entry.unit_price == 0.025
    assert entry.unit == "image"
    assert entry.currency == "USD"


def test_price_entry_accepts_id_alias_for_endpoint_id():
    entry = PriceEntry.model_validate({"id": "fal-ai/x", "unit_price": 0.1, "unit": "image"})
    assert entry.endpoint_id == "fal-ai/x"


def test_price_entry_accepts_price_alias_for_unit_price():
    entry = PriceEntry.model_validate(
        {"endpoint_id": "fal-ai/x", "price": 0.15, "unit": "megapixel"}
    )
    assert entry.unit_price == 0.15


def test_price_entry_accepts_pricing_unit_alias_for_unit():
    entry = PriceEntry.model_validate(
        {"endpoint_id": "fal-ai/x", "unit_price": 0.07, "pricing_unit": "second"}
    )
    assert entry.unit == "second"


def test_price_entry_currency_defaults_to_usd():
    entry = PriceEntry.model_validate({"endpoint_id": "fal-ai/x", "unit_price": 0.01, "unit": "image"})
    assert entry.currency == "USD"


def test_price_entry_zero_price_kept_as_zero_not_none():
    """Some endpoints might price at zero (free tier). Don't coerce to None."""
    entry = PriceEntry.model_validate(
        {"endpoint_id": "fal-ai/x", "unit_price": 0, "unit": "image"}
    )
    assert entry.unit_price == 0.0
    assert entry.unit_price is not None


def test_price_entry_missing_unit_price_is_none():
    entry = PriceEntry.model_validate({"endpoint_id": "fal-ai/x", "unit": "image"})
    assert entry.unit_price is None


def test_price_entry_extra_fields_are_ignored():
    """Future fields fal might add shouldn't break parsing."""
    entry = PriceEntry.model_validate(
        {
            "endpoint_id": "fal-ai/x",
            "unit_price": 0.01,
            "unit": "image",
            "future_field": "ignored",
            "metadata": {"x": 1},
        }
    )
    assert entry.endpoint_id == "fal-ai/x"


# ---- PricingPage: envelope aliases ------------------------------------


def test_pricing_page_canonical_envelope():
    page = PricingPage.model_validate(
        {"prices": [{"endpoint_id": "fal-ai/x", "unit_price": 0.01, "unit": "image"}], "has_more": False}
    )
    assert len(page.prices) == 1
    assert page.prices[0].endpoint_id == "fal-ai/x"


def test_pricing_page_accepts_models_envelope():
    page = PricingPage.model_validate(
        {"models": [{"endpoint_id": "fal-ai/x", "unit_price": 0.01, "unit": "image"}]}
    )
    assert len(page.prices) == 1


def test_pricing_page_accepts_data_envelope():
    page = PricingPage.model_validate(
        {"data": [{"endpoint_id": "fal-ai/x", "unit_price": 0.01, "unit": "image"}]}
    )
    assert len(page.prices) == 1


def test_pricing_page_empty_when_no_known_envelope():
    """If the response uses an unknown envelope key, parse to empty rather than raise."""
    page = PricingPage.model_validate({"unknown_envelope": [{"x": 1}]})
    assert page.prices == []


def test_pricing_page_pagination_fields():
    page = PricingPage.model_validate(
        {"prices": [], "next_cursor": "page-2", "has_more": True}
    )
    assert page.next_cursor == "page-2"
    assert page.has_more is True


# ---- Cache file round-trip --------------------------------------------


def test_pricing_cache_file_round_trip():
    original = PricingCacheFile(
        schema_version=1,
        fetched_at="2026-05-02T12:00:00+00:00",
        prices={"fal-ai/x": {"unit_price": 0.025, "unit": "image", "currency": "USD"}},
        no_pricing=["fal-ai/no-pricing"],
    )
    restored = PricingCacheFile.model_validate_json(original.model_dump_json())
    assert restored.schema_version == 1
    assert restored.fetched_at == "2026-05-02T12:00:00+00:00"
    assert restored.prices == original.prices
    assert restored.no_pricing == ["fal-ai/no-pricing"]


def test_pricing_cache_file_handles_missing_optional_fields():
    """Old caches missing `no_pricing` should default to empty list, not raise."""
    cache = PricingCacheFile.model_validate(
        {"schema_version": 1, "fetched_at": "2026-05-02T12:00:00+00:00", "prices": {}}
    )
    assert cache.no_pricing == []


def test_catalog_cache_file_round_trip():
    original = CatalogCacheFile(
        schema_version=5,
        fetched_at="2026-05-02T12:00:00+00:00",
        models=[
            {"id": "fal-ai/x", "display_name": "X", "category": "image-to-video", "shape": "single_image"}
        ],
    )
    restored = CatalogCacheFile.model_validate_json(original.model_dump_json())
    assert restored.schema_version == 5
    assert len(restored.models) == 1


# ---- HTTP response shapes ---------------------------------------------


def test_error_response_serializes_to_expected_dict():
    err = ErrorResponse(error="bad request")
    assert err.model_dump() == {"ok": False, "error": "bad request"}


def test_schema_response_serializes_to_expected_dict():
    resp = SchemaResponse(
        model_id="fal-ai/flux/dev",
        display_name="FLUX dev",
        category="text-to-image",
        shape="text_only",
        widgets=[{"name": "prompt", "kind": "STRING"}],
        unit_price=0.025,
        unit="image",
        currency="USD",
    )
    d = resp.model_dump()
    assert d["ok"] is True
    assert d["model_id"] == "fal-ai/flux/dev"
    assert d["unit_price"] == 0.025
    assert d["widgets"] == [{"name": "prompt", "kind": "STRING"}]


def test_schema_response_pricing_fields_default_to_none():
    resp = SchemaResponse(
        model_id="fal-ai/x", display_name="X", category="llm", shape="text_only", widgets=[]
    )
    d = resp.model_dump()
    assert d["unit_price"] is None
    assert d["unit"] is None
    assert d["currency"] is None


def test_refresh_response_serializes_to_expected_dict():
    resp = RefreshResponse(deleted=True, message="Cache cleared")
    assert resp.model_dump() == {"ok": True, "deleted": True, "message": "Cache cleared"}


def test_health_response_has_no_ok_envelope():
    """Health is a pure diagnostic; no `ok` field."""
    resp = HealthResponse(fal_key_present=True, model_count=925)
    d = resp.model_dump()
    assert "ok" not in d
    assert d["fal_key_present"] is True
    assert d["model_count"] == 925


def test_pricing_refresh_response_serializes_to_expected_dict():
    resp = PricingRefreshResponse(started=True, message="Pricing fetch started")
    d = resp.model_dump()
    assert d["ok"] is True
    assert d["started"] is True
