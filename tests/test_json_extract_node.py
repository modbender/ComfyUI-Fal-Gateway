"""Tests for FalGatewayJsonExtract — the companion node that fans a JSON
STRING (typically from T2T/I2T in schema mode) out into individual STRING
values keyed by field name."""

from __future__ import annotations

import json

from src.nodes.json_extract import FalGatewayJsonExtract


def _execute(json_string: str, key: str, default: str = "") -> str:
    (value,) = FalGatewayJsonExtract().execute(json_string=json_string, key=key, default=default)
    return value


def test_extract_returns_value_for_present_key():
    payload = json.dumps({"title": "Run Free", "tagline": "Comfort meets speed"})
    assert _execute(payload, "title") == "Run Free"
    assert _execute(payload, "tagline") == "Comfort meets speed"


def test_extract_returns_default_for_missing_key():
    payload = json.dumps({"title": "x"})
    assert _execute(payload, "tagline", default="N/A") == "N/A"
    assert _execute(payload, "tagline") == ""


def test_extract_returns_default_for_malformed_json():
    assert _execute("not even close to JSON", "title", default="bad") == "bad"
    assert _execute("{broken", "title") == ""


def test_extract_returns_default_for_non_dict_root():
    """A JSON list at the root has no string keys — fall back to default."""
    assert _execute("[1, 2, 3]", "title", default="!") == "!"
    assert _execute('"just a string"', "title") == ""


def test_extract_coerces_non_string_values_to_string():
    payload = json.dumps({"count": 42, "ratio": 0.5, "flag": True})
    assert _execute(payload, "count") == "42"
    assert _execute(payload, "ratio") == "0.5"
    assert _execute(payload, "flag") == "True"


def test_extract_coerces_nested_object_to_json_string():
    """Nested objects/arrays are serialized so downstream nodes still get a STRING."""
    payload = json.dumps({"meta": {"x": 1, "y": 2}})
    out = _execute(payload, "meta")
    # round-trip parseable
    assert json.loads(out) == {"x": 1, "y": 2}


def test_extract_handles_null_value_via_default():
    payload = json.dumps({"title": None})
    assert _execute(payload, "title", default="missing") == "missing"


def test_node_metadata_shape():
    """ComfyUI requires class-level RETURN_TYPES, RETURN_NAMES, FUNCTION,
    CATEGORY, and an INPUT_TYPES classmethod."""
    cls = FalGatewayJsonExtract
    assert cls.RETURN_TYPES == ("STRING",)
    assert cls.RETURN_NAMES == ("value",)
    assert cls.FUNCTION == "execute"
    assert cls.CATEGORY.startswith("Fal-Gateway")
    spec = cls.INPUT_TYPES()
    assert "json_string" in spec["required"]
    assert "key" in spec["required"]
    assert "default" in spec["optional"]
