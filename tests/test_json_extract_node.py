"""Tests for FalGatewayJsonExtract — the companion node that fans a JSON
STRING (typically from T2T/I2T in schema mode) out into individual STRING
values keyed by field name."""

from __future__ import annotations

import json

from src.nodes.json_extract import FalGatewayJsonExtract, FalGatewayJsonExtractMany


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


# ---- FalGatewayJsonExtractMany ------------------------------------------
#
# Single multiline `keys` textarea (comma-separated). N output sockets
# named after the parsed keys, count auto-syncs as the user edits the
# textarea. Python returns exactly MAX_OUTPUTS values; slots past
# len(parsed_keys) get the `default` value.
#
# Why textarea instead of per-row widgets: LiteGraph's computeSize hard-
# codes rows = max(inputs, outputs) and stacks widgets BELOW the slot
# strip — per-row widgets create an unfixable layout mismatch (left
# column has visible widgets, right column has output dots, no way to
# align them without writing custom canvas-drawn row widgets the way
# rgthree's Power LoRA Loader does — significantly more code, fragile
# across LG versions). One textarea sidesteps the whole layout fight.


def _execute_many(json_string: str, keys: str, default: str = "") -> tuple[str, ...]:
    return FalGatewayJsonExtractMany().execute(
        json_string=json_string, keys=keys, default=default,
    )


def test_many_extracts_in_key_order_and_pads_to_max():
    """Five keys → first five outputs hold the values, rest are empty strings."""
    payload = json.dumps({
        "title": "Run Free", "tagline": "speed", "cta": "Buy",
        "audience": "runners", "tone": "energetic",
    })
    out = _execute_many(payload, "title, tagline, cta, audience, tone")
    assert len(out) == FalGatewayJsonExtractMany.MAX_OUTPUTS
    assert out[:5] == ("Run Free", "speed", "Buy", "runners", "energetic")
    assert out[5:] == ("",) * (FalGatewayJsonExtractMany.MAX_OUTPUTS - 5)


def test_many_uses_default_per_missing_key():
    """Per-key default applied independently — present keys still come through."""
    payload = json.dumps({"title": "x"})
    out = _execute_many(payload, "title, tagline, cta", default="MISSING")
    assert out[:3] == ("x", "MISSING", "MISSING")


def test_many_handles_malformed_json_with_default_for_every_key():
    """Parse failure → every requested key gets the default."""
    out = _execute_many("{not json", "a, b, c", default="X")
    assert out[:3] == ("X", "X", "X")


def test_many_strips_whitespace_and_drops_empty_segments():
    """`'  a , , b ,'` → keys ['a', 'b']. Empty segments between commas
    are dropped so a stray comma doesn't create a phantom output slot."""
    payload = json.dumps({"a": "1", "b": "2"})
    out = _execute_many(payload, "  a , , b ,")
    assert out[:2] == ("1", "2")
    assert out[2] == ""


def test_many_caps_at_max_outputs():
    """More keys than MAX_OUTPUTS → silently drop the overflow."""
    keys = ", ".join(f"k{i}" for i in range(20))
    payload = json.dumps({f"k{i}": f"v{i}" for i in range(20)})
    out = _execute_many(payload, keys)
    assert len(out) == FalGatewayJsonExtractMany.MAX_OUTPUTS
    assert out == tuple(f"v{i}" for i in range(FalGatewayJsonExtractMany.MAX_OUTPUTS))


def test_many_coerces_non_string_values():
    """Same coercion rules as Single — int/float/bool stringified, dict/list
    serialized as JSON."""
    payload = json.dumps({"n": 7, "f": 0.25, "b": False, "obj": {"x": 1}})
    out = _execute_many(payload, "n, f, b, obj")
    assert out[:4] == ("7", "0.25", "False", '{"x": 1}')


def test_many_null_value_uses_default():
    payload = json.dumps({"title": None, "tagline": "ok"})
    out = _execute_many(payload, "title, tagline", default="N/A")
    assert out[:2] == ("N/A", "ok")


def test_many_empty_keys_returns_all_padding():
    """No keys at all → every output slot is the empty string. Not an error."""
    out = _execute_many('{"a": 1}', "")
    assert out == ("",) * FalGatewayJsonExtractMany.MAX_OUTPUTS


def test_many_node_metadata_shape():
    """ComfyUI contract: RETURN_TYPES length == RETURN_NAMES length == MAX_OUTPUTS.
    The JS extension relies on this contract — if MAX_OUTPUTS bumps here, it
    must bump in fal_gateway.js too. This test is the canary.

    Also pins the input-types shape: a single multiline `keys` STRING widget.
    """
    cls = FalGatewayJsonExtractMany
    assert cls.MAX_OUTPUTS == 10
    assert len(cls.RETURN_TYPES) == cls.MAX_OUTPUTS
    assert len(cls.RETURN_NAMES) == cls.MAX_OUTPUTS
    assert all(t == "STRING" for t in cls.RETURN_TYPES)
    assert cls.RETURN_NAMES == tuple(f"value_{i + 1}" for i in range(cls.MAX_OUTPUTS))
    assert cls.FUNCTION == "execute"
    assert cls.CATEGORY.startswith("Fal-Gateway")

    spec = cls.INPUT_TYPES()
    assert "json_string" in spec["required"]
    assert "keys" in spec["required"]
    assert "default" in spec["optional"]
    keys_type, keys_meta = spec["required"]["keys"]
    assert keys_type == "STRING"
    assert keys_meta.get("multiline") is True, "keys widget should be a textarea"
