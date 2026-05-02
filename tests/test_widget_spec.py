"""Tests for WidgetSpec / ModelEntry serialization, focused on the pricing
round-trip introduced in v0.4.0.

The cache file format MUST stay backward compatible: a v3 cache (no pricing
fields) loads cleanly under the new code, and a v4 cache round-trips
unit_price/unit/currency without loss.
"""

from __future__ import annotations

from src.widget_spec import ModelEntry, WidgetSpec


def _entry(**overrides) -> ModelEntry:
    base = dict(
        id="fal-ai/flux/dev",
        display_name="FLUX.1 [dev]",
        category="text-to-image",
        shape="text_only",
        description="",
        widgets=[],
    )
    base.update(overrides)
    return ModelEntry(**base)


def test_to_dict_includes_pricing_fields_when_set():
    entry = _entry(unit_price=0.025, unit="image", currency="USD")
    d = entry.to_dict()
    assert d["unit_price"] == 0.025
    assert d["unit"] == "image"
    assert d["currency"] == "USD"


def test_to_dict_includes_none_pricing_when_unset():
    entry = _entry()
    d = entry.to_dict()
    assert d["unit_price"] is None
    assert d["unit"] is None
    assert d["currency"] is None


def test_from_dict_round_trips_pricing():
    entry = _entry(unit_price=0.30, unit="second", currency="USD")
    restored = ModelEntry.from_dict(entry.to_dict())
    assert restored.unit_price == 0.30
    assert restored.unit == "second"
    assert restored.currency == "USD"


def test_from_dict_handles_old_cache_without_pricing_keys():
    """A v3-format cache entry must deserialize without error and yield
    None pricing — old caches in the wild stay valid until SCHEMA_VERSION
    invalidation kicks in."""
    legacy = {
        "id": "fal-ai/flux/dev",
        "display_name": "FLUX.1 [dev]",
        "category": "text-to-image",
        "shape": "text_only",
        "description": "",
        "widgets": [],
    }
    restored = ModelEntry.from_dict(legacy)
    assert restored.unit_price is None
    assert restored.unit is None
    assert restored.currency is None


def test_from_dict_carries_widgets_alongside_pricing():
    entry = _entry(
        widgets=[WidgetSpec(name="prompt", kind="STRING", required=True, multiline=True)],
        unit_price=0.05,
        unit="image",
        currency="USD",
    )
    restored = ModelEntry.from_dict(entry.to_dict())
    assert len(restored.widgets) == 1
    assert restored.widgets[0].name == "prompt"
    assert restored.unit_price == 0.05
