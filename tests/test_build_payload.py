"""Tests for _FalGatewayNodeBase._build_payload — the kwarg→fal-payload mapper.

This is the M4 contract: when the frontend renders dynamic widgets and the
user sets values, those values must end up in the fal payload at the
WidgetSpec's `payload_key`. Regressions here would silently re-enable the
"every call uses model defaults" cost bug.

We test text-only models so we don't have to mock fal_client image uploads.
Image-input handling is exercised via the M3 integration suite.
"""

from __future__ import annotations

import pytest

from src.overrides import apply_payload_transformer
from src.nodes.base import _FalGatewayNodeBase
from src.widget_spec import ModelEntry, WidgetSpec


def _t2v_entry(extra_widgets: list[WidgetSpec]) -> ModelEntry:
    """Build a synthetic text-to-video ModelEntry for payload tests."""
    base = [
        WidgetSpec(
            name="prompt",
            kind="STRING",
            default="",
            required=True,
            multiline=True,
            payload_key="prompt",
        ),
    ]
    return ModelEntry(
        id="test/synthetic-t2v",
        display_name="Synthetic T2V",
        category="text-to-video",
        shape="text_only",
        widgets=base + extra_widgets,
    )


@pytest.fixture
def node():
    return _FalGatewayNodeBase()


# ---- prompt handling ------------------------------------------------------


async def test_build_payload_includes_prompt_when_provided(node):
    entry = _t2v_entry([])
    payload = await node._build_payload(entry, "a sunset", {})
    assert payload == {"prompt": "a sunset"}


async def test_build_payload_omits_prompt_when_empty(node):
    """Empty prompt shouldn't end up in payload — fal expects either present or absent."""
    entry = _t2v_entry([])
    payload = await node._build_payload(entry, "", {})
    assert "prompt" not in payload


# ---- the M4 contract: dynamic widget kwargs -------------------------------


async def test_build_payload_uses_kwarg_value_for_int_widget(node):
    entry = _t2v_entry([
        WidgetSpec(name="seed", kind="INT", default=0, payload_key="seed"),
    ])
    payload = await node._build_payload(entry, "x", {"seed": 12345})
    assert payload["seed"] == 12345


async def test_build_payload_uses_kwarg_value_for_combo_widget(node):
    entry = _t2v_entry([
        WidgetSpec(
            name="duration",
            kind="COMBO",
            default="auto",
            options=["auto", "4", "5"],
            payload_key="duration",
        ),
    ])
    payload = await node._build_payload(entry, "x", {"duration": "5"})
    assert payload["duration"] == "5"


async def test_build_payload_uses_kwarg_value_for_boolean_widget(node):
    entry = _t2v_entry([
        WidgetSpec(name="generate_audio", kind="BOOLEAN", default=True, payload_key="generate_audio"),
    ])
    payload = await node._build_payload(entry, "x", {"generate_audio": False})
    assert payload["generate_audio"] is False


async def test_build_payload_uses_kwarg_value_for_float_widget(node):
    entry = _t2v_entry([
        WidgetSpec(name="cfg_scale", kind="FLOAT", default=0.5, payload_key="cfg_scale"),
    ])
    payload = await node._build_payload(entry, "x", {"cfg_scale": 0.85})
    assert payload["cfg_scale"] == pytest.approx(0.85)


# ---- payload_key vs name ---------------------------------------------------


async def test_build_payload_maps_widget_name_to_distinct_payload_key(node):
    """When WidgetSpec.payload_key differs from name (e.g. image_1 → tail_image_url),
    the kwarg key (frontend widget name) maps to the payload key (fal field name)."""
    entry = _t2v_entry([
        WidgetSpec(
            name="ui_negative",  # what the widget is called
            kind="STRING",
            default="",
            payload_key="negative_prompt",  # what fal expects
        ),
    ])
    payload = await node._build_payload(entry, "x", {"ui_negative": "blurry, low quality"})
    assert "ui_negative" not in payload
    assert payload["negative_prompt"] == "blurry, low quality"


# ---- defaults vs explicit values ------------------------------------------


async def test_build_payload_omits_widget_when_kwarg_missing_and_default_empty(node):
    entry = _t2v_entry([
        WidgetSpec(name="end_user_id", kind="STRING", default="", payload_key="end_user_id"),
    ])
    payload = await node._build_payload(entry, "x", {})
    assert "end_user_id" not in payload, "empty default shouldn't be sent to fal"


async def test_build_payload_includes_widget_when_kwarg_missing_but_default_non_empty(node):
    """A widget with a non-empty default and no kwarg override should send the default."""
    entry = _t2v_entry([
        WidgetSpec(
            name="aspect_ratio",
            kind="COMBO",
            default="16:9",
            options=["16:9", "9:16"],
            payload_key="aspect_ratio",
        ),
    ])
    payload = await node._build_payload(entry, "x", {})
    assert payload["aspect_ratio"] == "16:9"


# ---- type coercion --------------------------------------------------------


async def test_build_payload_coerces_string_kwarg_to_int_for_int_widget(node):
    """ComfyUI's number widget often round-trips values as strings; backend coerces."""
    entry = _t2v_entry([
        WidgetSpec(name="seed", kind="INT", default=0, payload_key="seed"),
    ])
    payload = await node._build_payload(entry, "x", {"seed": "42"})
    assert payload["seed"] == 42
    assert isinstance(payload["seed"], int)


async def test_build_payload_coerces_string_kwarg_to_float_for_float_widget(node):
    entry = _t2v_entry([
        WidgetSpec(name="cfg", kind="FLOAT", default=0.5, payload_key="cfg"),
    ])
    payload = await node._build_payload(entry, "x", {"cfg": "0.7"})
    assert payload["cfg"] == pytest.approx(0.7)


async def test_build_payload_coerces_string_kwarg_to_bool_for_boolean_widget(node):
    entry = _t2v_entry([
        WidgetSpec(name="flag", kind="BOOLEAN", default=False, payload_key="flag"),
    ])
    payload = await node._build_payload(entry, "x", {"flag": "true"})
    assert payload["flag"] is True


# ---- multiple widgets simultaneously --------------------------------------


async def test_build_payload_handles_full_seedance_2_style_kwarg_set(node):
    """End-to-end shape: a Seedance-2-like model with the full set of widgets the
    frontend would render. User overrides duration + aspect_ratio; rest take defaults
    (and the no-default ones are dropped)."""
    entry = _t2v_entry([
        WidgetSpec(name="aspect_ratio", kind="COMBO", default="auto",
                   options=["auto", "16:9", "9:16"], payload_key="aspect_ratio"),
        WidgetSpec(name="duration", kind="COMBO", default="auto",
                   options=["auto", "4", "5", "6"], payload_key="duration"),
        WidgetSpec(name="resolution", kind="COMBO", default="720p",
                   options=["480p", "720p", "1080p"], payload_key="resolution"),
        WidgetSpec(name="seed", kind="INT", default=0, payload_key="seed"),
        WidgetSpec(name="generate_audio", kind="BOOLEAN", default=True,
                   payload_key="generate_audio"),
    ])
    payload = await node._build_payload(
        entry,
        "a tiger on a snowy ridge",
        {"duration": "5", "aspect_ratio": "9:16"},
    )
    assert payload["prompt"] == "a tiger on a snowy ridge"
    assert payload["duration"] == "5"
    assert payload["aspect_ratio"] == "9:16"
    assert payload["resolution"] == "720p"  # default carried
    assert payload["seed"] == 0  # default carried
    assert payload["generate_audio"] is True  # default carried


# ---- catalog-driven dispatch (T2T/I2T) ----------------------------------
#
# After K1, the OpenRouter chat-completions endpoint is reached via the
# curated T2T catalog rather than per-endpoint widget overrides. The
# integration is: `_build_payload(None, prompt, kwargs)` → merge catalog
# `extra_payload` → `apply_payload_transformer(endpoint_id, payload)`.
# These tests verify the assembled payload at each step.


async def test_build_payload_catalog_path_passes_static_widgets_through(node):
    """When `entry` is None (catalog dispatch), _build_payload just stages
    the prompt + any static node-level widgets (system_prompt) in the
    payload for the transformer to reshape."""
    payload = await node._build_payload(
        None,
        "Hello there.",
        {"system_prompt": "Be terse."},
    )
    assert payload == {"prompt": "Hello there.", "system_prompt": "Be terse."}


async def test_catalog_dispatch_to_chat_completions_end_to_end(node):
    """Full catalog dispatch: build → merge extra_payload → transform."""
    payload = await node._build_payload(
        None,
        "Hello there.",
        {"system_prompt": "Be terse."},
    )
    # catalog entry's extra_payload — what the T2T curated registry injects
    payload = {**payload, **{"model": "anthropic/claude-sonnet-4.5"}}
    payload = apply_payload_transformer(
        "openrouter/router/openai/v1/chat/completions", payload
    )
    assert "prompt" not in payload
    assert "system_prompt" not in payload
    assert payload["model"] == "anthropic/claude-sonnet-4.5"
    assert payload["messages"] == [
        {"role": "system", "content": "Be terse."},
        {"role": "user", "content": "Hello there."},
    ]


async def test_catalog_dispatch_with_empty_system_prompt(node):
    payload = await node._build_payload(None, "What time is it?", {"system_prompt": ""})
    payload = {**payload, **{"model": "openai/gpt-4o"}}
    payload = apply_payload_transformer(
        "openrouter/router/openai/v1/chat/completions", payload
    )
    assert payload["messages"] == [{"role": "user", "content": "What time is it?"}]


async def test_build_payload_no_transform_for_other_endpoints(node):
    """Non-openrouter endpoints must NOT get the messages-shape transform applied."""
    entry = _t2v_entry([])
    payload = await node._build_payload(entry, "test prompt", {})
    assert payload == {"prompt": "test prompt"}
    assert "messages" not in payload
