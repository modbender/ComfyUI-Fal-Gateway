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
# R2V-style multi-key fan-out. `key_count` (INT, +/-) drives both how many
# `key_N` widgets are visible (JS) and how many output sockets show up.
# Each `key_N` is a single-line STRING widget the user types one key into.
# Python returns exactly MAX_OUTPUTS values; trailing slots are empty.


def _execute_many(
    json_string: str,
    key_count: int,
    *,
    default: str = "",
    **keys: str,
) -> tuple[str, ...]:
    return FalGatewayJsonExtractMany().execute(
        json_string=json_string, key_count=key_count, default=default, **keys,
    )


def test_many_extracts_in_key_order_and_pads_to_max():
    """Five keys → first five outputs hold the values, rest are empty strings."""
    payload = json.dumps({
        "title": "Run Free", "tagline": "speed", "cta": "Buy",
        "audience": "runners", "tone": "energetic",
    })
    out = _execute_many(
        payload, 5,
        key_1="title", key_2="tagline", key_3="cta",
        key_4="audience", key_5="tone",
    )
    assert len(out) == FalGatewayJsonExtractMany.MAX_OUTPUTS
    assert out[:5] == ("Run Free", "speed", "Buy", "runners", "energetic")
    assert out[5:] == ("",) * (FalGatewayJsonExtractMany.MAX_OUTPUTS - 5)


def test_many_uses_default_per_missing_key():
    """Per-key default applied independently — present keys still come through."""
    payload = json.dumps({"title": "x"})
    out = _execute_many(
        payload, 3,
        key_1="title", key_2="tagline", key_3="cta",
        default="MISSING",
    )
    assert out[:3] == ("x", "MISSING", "MISSING")


def test_many_handles_malformed_json_with_default_for_every_key():
    """Parse failure → every requested key gets the default."""
    out = _execute_many(
        "{not json", 3,
        key_1="a", key_2="b", key_3="c",
        default="X",
    )
    assert out[:3] == ("X", "X", "X")


def test_many_strips_whitespace_per_key_widget():
    """Per-key whitespace stripped — '  title  ' resolves to 'title'."""
    payload = json.dumps({"title": "x", "tagline": "y"})
    out = _execute_many(
        payload, 2,
        key_1="  title  ", key_2="tagline",
    )
    assert out[:2] == ("x", "y")


def test_many_empty_key_widget_returns_default_for_that_slot():
    """An empty `key_N` (user hasn't typed anything yet) returns the default
    for that slot — the other slots still resolve normally."""
    payload = json.dumps({"title": "x", "cta": "z"})
    out = _execute_many(
        payload, 3,
        key_1="title", key_2="", key_3="cta",
        default="-",
    )
    assert out[:3] == ("x", "-", "z")


def test_many_clamps_key_count_into_valid_range():
    """key_count = 0 → treat as 1; key_count > MAX → clamp to MAX. Belt and
    braces against stale workflow JSON or hand-edits."""
    payload = json.dumps({"a": "v"})
    # 0 → 1
    out = _execute_many(payload, 0, key_1="a")
    assert out[0] == "v"
    # Way over MAX → clamped, but extra key_N widgets still ignored beyond MAX
    keys_kw = {f"key_{i}": f"k{i}" for i in range(1, 21)}
    payload_full = json.dumps({f"k{i}": f"v{i}" for i in range(1, 21)})
    out = _execute_many(payload_full, 999, **keys_kw)
    assert len(out) == FalGatewayJsonExtractMany.MAX_OUTPUTS
    expected = tuple(f"v{i}" for i in range(1, FalGatewayJsonExtractMany.MAX_OUTPUTS + 1))
    assert out == expected


def test_many_only_evaluates_keys_up_to_key_count():
    """Widgets beyond key_count are ignored even if the user typed values
    into them earlier (stays consistent with what's visible in the UI)."""
    payload = json.dumps({"a": "1", "b": "2", "c": "3"})
    out = _execute_many(
        payload, 1,
        key_1="a", key_2="b", key_3="c",  # b and c set but key_count=1
    )
    assert out[0] == "1"
    assert out[1:] == ("",) * (FalGatewayJsonExtractMany.MAX_OUTPUTS - 1)


def test_many_coerces_non_string_values():
    """Same coercion rules as Single — int/float/bool stringified, dict/list
    serialized as JSON."""
    payload = json.dumps({"n": 7, "f": 0.25, "b": False, "obj": {"x": 1}})
    out = _execute_many(
        payload, 4,
        key_1="n", key_2="f", key_3="b", key_4="obj",
    )
    assert out[:4] == ("7", "0.25", "False", '{"x": 1}')


def test_many_null_value_uses_default():
    payload = json.dumps({"title": None, "tagline": "ok"})
    out = _execute_many(
        payload, 2,
        key_1="title", key_2="tagline",
        default="N/A",
    )
    assert out[:2] == ("N/A", "ok")


def test_many_node_metadata_shape():
    """ComfyUI contract: RETURN_TYPES length == RETURN_NAMES length == MAX_OUTPUTS.
    The JS extension relies on this contract — if MAX_OUTPUTS bumps here, it
    must bump in fal_gateway.js too. This test is the canary.

    Also pins the input-types shape: key_count INT widget with +/- range,
    plus key_1..key_MAX_OUTPUTS single-line STRING widgets."""
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
    assert "default" in spec["optional"]

    # key_count is an INT spinner with +/- arrows in the UI.
    kc_type, kc_meta = spec["required"]["key_count"]
    assert kc_type == "INT"
    assert kc_meta["min"] == 1
    assert kc_meta["max"] == cls.MAX_OUTPUTS
    assert kc_meta["step"] == 1
    assert kc_meta["default"] == 1

    # All key_1..key_MAX_OUTPUTS declared as single-line STRING widgets so
    # ComfyUI serializes/restores them across save+load cleanly.
    for i in range(1, cls.MAX_OUTPUTS + 1):
        key_name = f"key_{i}"
        assert key_name in spec["required"], f"missing {key_name} in INPUT_TYPES"
        kt, kmeta = spec["required"][key_name]
        assert kt == "STRING"
        assert kmeta.get("multiline") is False, f"{key_name} should be single-line"
