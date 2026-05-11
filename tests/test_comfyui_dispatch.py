"""Tests that route node calls through a ComfyUI-faithful kwarg filter.

The other test files call `node.execute(**kwargs)` directly. That misses
the class of bug where a widget value lives in node.widgets but is
silently dropped before reaching execute() — which is exactly how the
FalGatewayJsonExtractMany "only key_1 returns data" regression slipped
through pytest.

These tests go through `tests/_dispatch.py::dispatch`, which mirrors the
INPUT_TYPES-based filter in ComfyUI's execution.py (see _dispatch.py
docstring for the reference). The promise: any test here would have
failed before the fix that declared key_2..key_10 in INPUT_TYPES.
"""

from __future__ import annotations

import json

from src.nodes.json_extract import FalGatewayJsonExtract, FalGatewayJsonExtractMany

from tests._dispatch import comfyui_kwarg_filter, dispatch


def test_dispatch_filter_drops_undeclared_widget_names():
    """Direct test of the filter: a widget value whose name isn't in
    INPUT_TYPES disappears. This is the bug class we shipped."""
    filtered = comfyui_kwarg_filter(
        FalGatewayJsonExtractMany,
        {
            "json_string": "{}",
            "key_count": 1,
            "default": "",
            "key_1": "title",
            # A name not in INPUT_TYPES — must be dropped.
            "completely_unknown_widget": "garbage",
        },
    )
    assert "completely_unknown_widget" not in filtered
    assert "key_1" in filtered  # sanity: declared names are kept


def test_dispatch_filter_keeps_all_declared_key_widgets():
    """The whole point of declaring key_2..key_MAX in INPUT_TYPES.optional
    is so the filter keeps them. This is the regression canary that the
    pure metadata test now pins from a different angle."""
    widgets = {
        "json_string": "{}",
        "key_count": 5,
        "default": "",
        **{f"key_{i}": f"k{i}" for i in range(1, FalGatewayJsonExtractMany.MAX_OUTPUTS + 1)},
    }
    filtered = comfyui_kwarg_filter(FalGatewayJsonExtractMany, widgets)
    for i in range(1, FalGatewayJsonExtractMany.MAX_OUTPUTS + 1):
        assert f"key_{i}" in filtered, (
            f"key_{i} dropped by the filter — execute() would never see it. "
            f"INPUT_TYPES must declare every key_N the JS extension can surface."
        )


def test_json_extract_many_multi_key_round_trip_through_dispatch():
    """End-to-end: widget values → dispatch filter → execute() → outputs.
    This is the test that would have failed before commit 4bfb9f3.

    Pre-fix, key_2..key_5 would be filtered out before reaching execute(),
    `**keys` would only contain key_1, and outputs 2..5 would come back
    as the default string. After the fix, all keys land and the values
    flow through correctly.
    """
    payload = json.dumps({
        "title": "Run Free",
        "tagline": "speed",
        "cta": "Buy",
        "audience": "runners",
        "tone": "energetic",
    })
    out = dispatch(
        FalGatewayJsonExtractMany,
        json_string=payload,
        key_count=5,
        default="DROPPED",
        key_1="title",
        key_2="tagline",
        key_3="cta",
        key_4="audience",
        key_5="tone",
    )
    assert out[:5] == ("Run Free", "speed", "Buy", "runners", "energetic"), (
        "If any slot is 'DROPPED', the filter dropped that key's widget "
        "value — meaning the corresponding key_N is not declared in "
        "INPUT_TYPES. Check src/nodes/json_extract.py:INPUT_TYPES."
    )
    assert out[5:] == ("",) * (FalGatewayJsonExtractMany.MAX_OUTPUTS - 5)


def test_json_extract_single_through_dispatch():
    """The single-output node only has one user-typed key widget, so it
    can't reproduce the multi-kwarg bug — but routing it through dispatch
    proves the helper itself works on a sync execute() and pins the basic
    contract."""
    payload = json.dumps({"title": "x"})
    out = dispatch(
        FalGatewayJsonExtract,
        json_string=payload,
        key="title",
        default="",
    )
    assert out == ("x",)
