"""Tests for WidgetSpec / ModelEntry serialization.

ModelEntry no longer carries pricing — pricing lives in src/storage/pricing.py
under cache/pricing.json. Tests here cover the catalog-only round-trip and
backward compatibility with v4 caches that DO have stray pricing keys (we
just ignore them).
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


def test_to_dict_round_trip():
    entry = _entry(
        widgets=[WidgetSpec(name="prompt", kind="STRING", required=True, multiline=True)],
    )
    restored = ModelEntry.from_dict(entry.to_dict())
    assert restored.id == entry.id
    assert restored.display_name == entry.display_name
    assert restored.category == entry.category
    assert restored.shape == entry.shape
    assert len(restored.widgets) == 1
    assert restored.widgets[0].name == "prompt"


def test_from_dict_ignores_legacy_pricing_keys():
    """v4 caches stored unit_price/unit/currency on the entry. v5 drops them
    silently — pricing now lives in the separate pricing.json cache."""
    legacy = {
        "id": "fal-ai/flux/dev",
        "display_name": "FLUX.1 [dev]",
        "category": "text-to-image",
        "shape": "text_only",
        "description": "",
        "widgets": [],
        "unit_price": 0.025,  # v4 leftover — must be ignored without raising
        "unit": "image",
        "currency": "USD",
    }
    restored = ModelEntry.from_dict(legacy)
    assert restored.id == "fal-ai/flux/dev"
    assert restored.display_name == "FLUX.1 [dev]"
    assert not hasattr(restored, "unit_price"), \
        "ModelEntry must not have pricing fields anymore"


def test_to_dict_excludes_pricing_fields():
    entry = _entry()
    d = entry.to_dict()
    assert "unit_price" not in d
    assert "unit" not in d
    assert "currency" not in d
