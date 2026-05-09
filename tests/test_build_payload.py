"""Tests for _FalGatewayNodeBase._build_payload — the kwarg→fal-payload mapper.

This is the M4 contract: when the frontend renders dynamic widgets and the
user sets values, those values must end up in the fal payload at the
WidgetSpec's `payload_key`. Regressions here would silently re-enable the
"every call uses model defaults" cost bug.

We test text-only models so we don't have to mock fal_client image uploads.
Image-input handling is exercised via the M3 integration suite.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.overrides import apply_payload_transformer
from src.nodes.base import _FalGatewayNodeBase
from src.nodes.i2t import FalGatewayI2T
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


# ---- I2T image socket plumbing -------------------------------------------
#
# Live-fetched vision models (Florence-2, Moondream, OpenRouter Vision) expose
# their image parameter under OpenAPI property names like "image_url" /
# "image_urls", not "image". The static ComfyUI socket is always named "image",
# so kwargs["image"] holds the tensor. _build_payload must bridge the gap.


async def test_i2t_maps_static_image_socket_to_widget_named_image_url():
    """Florence-2-shaped entry: widget name='image_url', static socket='image'.
    Tensor must reach payload at fal_key='image_url'."""
    entry = ModelEntry(
        id="fal-ai/florence-2-large/detailed-caption",
        display_name="Florence-2 Large",
        category="vision",
        shape="single_image",
        widgets=[
            WidgetSpec(name="image_url", kind="IMAGE_INPUT", required=True,
                       payload_key="image_url"),
        ],
        input_modalities=["text", "image"],
    )
    fake_tensor = object()
    with patch("src.nodes.base.upload_tensor_image",
               new=AsyncMock(return_value="https://fal.media/uploaded.png")):
        node = FalGatewayI2T()
        payload = await node._build_payload(entry, prompt="describe", kwargs={"image": fake_tensor})
    assert payload["image_url"] == "https://fal.media/uploaded.png"


async def test_i2t_image_array_widget_gets_list_not_bare_url():
    """openrouter/router/vision shape: IMAGE_ARRAY widget at fal_key='image_urls'.
    Payload must hold a LIST of URLs."""
    entry = ModelEntry(
        id="openrouter/router/vision",
        display_name="OpenRouter Vision",
        category="vision",
        shape="multi_ref",
        widgets=[
            WidgetSpec(name="image_urls", kind="IMAGE_ARRAY", required=True,
                       payload_key="image_urls"),
            WidgetSpec(name="prompt", kind="STRING", payload_key="prompt"),
        ],
        input_modalities=["text", "image"],
    )
    fake_tensor = object()
    with patch("src.nodes.base.upload_tensor_image",
               new=AsyncMock(return_value="https://fal.media/uploaded.png")):
        node = FalGatewayI2T()
        payload = await node._build_payload(entry, prompt="describe", kwargs={"image": fake_tensor})
    assert payload["image_urls"] == ["https://fal.media/uploaded.png"]


# ---- I2T OpenRouter vision catalog integration --------------------------
#
# Tasks 5-7 unified OpenRouter vision dispatch: fetch models → synthesize
# CatalogEntry rows with endpoint_id="openrouter/router/vision" and
# extra_payload={"model": "<id>"}. This integration test locks in the full
# path: fake cache → _build_curated() → catalog resolve → correct entry shape.


def test_i2t_openrouter_vision_e2e_payload(monkeypatch):
    """End-to-end: I2T catalog row '[Anthropic] Claude Sonnet 4.5' resolves
    to a CatalogEntry pointing at openrouter/router/vision with the right
    extra_payload — locks in Tasks 5-7 working together end-to-end."""
    from src.catalogs import i2t
    from src import catalogs as catalogs_pkg

    fake_or_models = [{
        "id": "anthropic/claude-sonnet-4.5",
        "name": "Claude Sonnet 4.5",
        "input_modalities": ["text", "image"],
        "description": "",
    }]
    monkeypatch.setattr(i2t, "_load_openrouter_models", lambda: fake_or_models)
    new_curated = i2t._build_curated()
    monkeypatch.setitem(catalogs_pkg._CATEGORY_CURATED, "vision", new_curated)

    # Empty live list isolates the test to the curated path.
    entry = catalogs_pkg.resolve("vision", "[Anthropic] Claude Sonnet 4.5", [])
    assert entry is not None
    assert entry.endpoint_id == "openrouter/router/vision"
    assert entry.extra_payload == {"model": "anthropic/claude-sonnet-4.5"}
    assert entry.provider == "anthropic"


# ---- Schema-mode (JSON output) wire-up ----------------------------------
#
# `schema` is a static widget on T2T/I2T (added via extra_required_widgets).
# It flows: kwargs → _build_payload pass-through → apply_schema_to_payload
# (which pops it and injects response_format for supported endpoints).
# These tests verify the full wire is intact end-to-end.


from src.json_mode import apply_schema_to_payload  # noqa: E402
from src.nodes.t2t import FalGatewayT2T  # noqa: E402


CHAT_ENDPOINT = "openrouter/router/openai/v1/chat/completions"
VISION_ENDPOINT = "openrouter/router/vision"
FAL_DIRECT_FLORENCE = "fal-ai/florence-2-large/detailed-caption"


async def test_t2t_schema_kwarg_yields_response_format_in_final_payload(node):
    """T2T + chat-completions: schema → response_format reaches the body fal sees."""
    # T2T uses catalog-driven dispatch (entry=None at this layer)
    payload = await FalGatewayT2T()._build_payload(
        None,
        "ad copy please",
        {"system_prompt": "You are concise.", "schema": "title, tagline, cta"},
    )
    # Catalog merge would add model id; simulate that step inline.
    payload = {**payload, "model": "anthropic/claude-sonnet-4.5"}
    payload = apply_schema_to_payload(payload, CHAT_ENDPOINT)
    final = apply_payload_transformer(CHAT_ENDPOINT, payload)

    assert "schema" not in final, "raw schema kwarg should not ship to fal"
    assert "response_format" in final
    assert final["response_format"]["json_schema"]["schema"]["required"] == [
        "title", "tagline", "cta",
    ]
    # Augmented system_prompt becomes the system message in the chat shape
    sys_msg = next(m for m in final["messages"] if m["role"] == "system")
    assert "title" in sys_msg["content"] and "JSON" in sys_msg["content"]


async def test_t2t_runtime_path_with_live_chat_entry_preserves_user_prompts():
    """REGRESSION: at runtime the live registry exposes
    `openrouter/router/openai/v1/chat/completions` as a ModelEntry (with a
    `prompt` widget), so execute()'s `entry = model_registry.get(...)` is
    non-None. _build_payload took the entry-is-not-None branch and called
    the chat transformer internally — then execute() called it AGAIN after
    apply_schema_to_payload. The second call clobbered the messages array
    that already held the user's system+user prompt with messages built only
    from the schema-augmented system_prompt, dropping the user's content.

    Symptom in the wild: T2T+schema returns generic LLM output unrelated to
    the user's system/user prompt.

    This test mirrors execute() exactly with a live-shaped chat entry."""
    chat_entry = ModelEntry(
        id="openrouter/router/openai/v1/chat/completions",
        display_name="OpenRouter Chat Completions",
        category="llm",
        shape="text_only",
        widgets=[WidgetSpec(name="prompt", kind="STRING", payload_key="prompt")],
    )
    user_system = "You are the creative director for Ferocine."
    user_prompt = "Invent one fresh clip concept."
    payload = await FalGatewayT2T()._build_payload(
        chat_entry,
        user_prompt,
        {"system_prompt": user_system, "schema": "title, tagline, cta"},
    )
    # execute() then merges catalog extra_payload, applies schema, transforms.
    payload = {**payload, "model": "anthropic/claude-sonnet-4.5"}
    payload = apply_schema_to_payload(payload, CHAT_ENDPOINT)
    final = apply_payload_transformer(CHAT_ENDPOINT, payload)

    assert "messages" in final, "transformer must wrap into chat messages shape"
    roles = [m["role"] for m in final["messages"]]
    assert "user" in roles, (
        f"USER message dropped — model never saw the user prompt. "
        f"messages={final['messages']}"
    )
    user_msg = next(m for m in final["messages"] if m["role"] == "user")
    assert user_msg["content"] == user_prompt
    sys_msg = next(m for m in final["messages"] if m["role"] == "system")
    # Original system content must survive AND be augmented with JSON instruction.
    assert user_system in sys_msg["content"], (
        f"USER's system_prompt dropped — model only sees JSON instruction. "
        f"system content={sys_msg['content']!r}"
    )
    assert "title" in sys_msg["content"] and "JSON" in sys_msg["content"]
    assert final["response_format"]["json_schema"]["schema"]["required"] == [
        "title", "tagline", "cta",
    ]


async def test_i2t_runtime_path_with_live_vision_entry_schema_produces_correct_payload():
    """REGRESSION counterpart to the T2T test: simulate execute()'s actual
    runtime path for I2T + openrouter/router/vision + schema. The vision
    endpoint accepts a FLAT shape (prompt, system_prompt, image_urls, model),
    has no transformer registered, and natively supports `system_prompt`.

    This test pins:
      1. image socket → image_urls list mapping
      2. schema → response_format injection
      3. system_prompt augmented with the JSON instruction
      4. user's text prompt preserved
      5. nothing leaks the raw `schema` key
      6. _build_payload no longer eats the prompt via a now-removed
         internal transformer call
    """
    vision_entry = ModelEntry(
        id=VISION_ENDPOINT,
        display_name="OpenRouter Vision",
        category="vision",
        shape="multi_ref",
        widgets=[
            WidgetSpec(name="image_urls", kind="IMAGE_ARRAY", required=True,
                       payload_key="image_urls"),
            WidgetSpec(name="prompt", kind="STRING", required=True,
                       payload_key="prompt"),
            WidgetSpec(name="system_prompt", kind="STRING", default="",
                       payload_key="system_prompt"),
            WidgetSpec(name="model", kind="STRING", default="",
                       payload_key="model"),
        ],
        input_modalities=["text", "image"],
    )
    fake_tensor = object()
    with patch("src.nodes.base.upload_tensor_image",
               new=AsyncMock(return_value="https://fal.media/img.png")):
        payload = await FalGatewayI2T()._build_payload(
            vision_entry,
            prompt="describe this animal",
            kwargs={"image": fake_tensor, "schema": "species, mood"},
        )
    payload = {**payload, "model": "anthropic/claude-sonnet-4.5"}
    payload = apply_schema_to_payload(payload, VISION_ENDPOINT)
    final = apply_payload_transformer(VISION_ENDPOINT, payload)

    assert final["prompt"] == "describe this animal"
    assert final["image_urls"] == ["https://fal.media/img.png"]
    assert final["model"] == "anthropic/claude-sonnet-4.5"
    assert "schema" not in final
    assert final["response_format"]["json_schema"]["schema"]["required"] == [
        "species", "mood",
    ]
    assert "Output STRICT JSON" in final["system_prompt"]
    assert "species" in final["system_prompt"]


async def test_i2t_schema_with_openrouter_vision_endpoint_yields_response_format():
    """I2T + openrouter/router/vision: schema → response_format end-to-end."""
    entry = ModelEntry(
        id=VISION_ENDPOINT,
        display_name="OpenRouter Vision",
        category="vision",
        shape="multi_ref",
        widgets=[
            WidgetSpec(name="image_urls", kind="IMAGE_ARRAY", required=True,
                       payload_key="image_urls"),
            WidgetSpec(name="prompt", kind="STRING", payload_key="prompt"),
        ],
        input_modalities=["text", "image"],
    )
    fake_tensor = object()
    with patch("src.nodes.base.upload_tensor_image",
               new=AsyncMock(return_value="https://fal.media/img.png")):
        payload = await FalGatewayI2T()._build_payload(
            entry,
            prompt="describe the animal",
            kwargs={"image": fake_tensor, "schema": "species, mood"},
        )
    payload = {**payload, "model": "anthropic/claude-sonnet-4.5"}
    final = apply_schema_to_payload(payload, VISION_ENDPOINT)

    assert "schema" not in final
    assert final["response_format"]["json_schema"]["schema"]["required"] == [
        "species", "mood",
    ]
    assert final["image_urls"] == ["https://fal.media/img.png"]


async def test_t2t_schema_with_fal_direct_llm_drops_schema_and_doesnt_synthesize_system_prompt(node):
    """Bytedance Seed / Nemotron-style fal-direct LLMs auto-merge into T2T but
    don't support response_format. Schema must be popped AND system_prompt
    must NOT be fabricated — those endpoints' OpenAPI schemas don't accept it."""
    payload = await FalGatewayT2T()._build_payload(
        None,
        "ad copy",
        {"system_prompt": "", "schema": "title, tagline"},
    )
    payload = {**payload, "model": "bytedance-seed-v1"}
    final = apply_schema_to_payload(payload, "fal-ai/bytedance-seed/v1")
    assert "schema" not in final
    assert "response_format" not in final
    assert "system_prompt" not in final


async def test_i2t_schema_with_fal_direct_endpoint_drops_schema_silently():
    """Florence-2 doesn't support response_format. The schema kwarg must be
    popped (so it doesn't ship to fal as an unknown field) and no
    response_format added."""
    entry = ModelEntry(
        id=FAL_DIRECT_FLORENCE,
        display_name="Florence-2 Large",
        category="vision",
        shape="single_image",
        widgets=[
            WidgetSpec(name="image_url", kind="IMAGE_INPUT", required=True,
                       payload_key="image_url"),
        ],
        input_modalities=["text", "image"],
    )
    fake_tensor = object()
    with patch("src.nodes.base.upload_tensor_image",
               new=AsyncMock(return_value="https://fal.media/img.png")):
        payload = await FalGatewayI2T()._build_payload(
            entry,
            prompt="describe",
            kwargs={"image": fake_tensor, "schema": "species, mood"},
        )
    final = apply_schema_to_payload(payload, FAL_DIRECT_FLORENCE)

    assert "schema" not in final
    assert "response_format" not in final
    assert "system_prompt" not in final, (
        "Florence-2 doesn't accept system_prompt; must not be fabricated"
    )
    assert final["image_url"] == "https://fal.media/img.png"
