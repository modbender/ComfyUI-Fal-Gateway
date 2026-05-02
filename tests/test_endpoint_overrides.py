"""Tests for src.endpoint_overrides — widget injection + payload reshape."""

from __future__ import annotations

from src.endpoint_overrides import (
    PAYLOAD_TRANSFORMERS,
    WIDGET_OVERRIDES,
    apply_payload_transformer,
    apply_widget_overrides,
)
from src.widget_spec import WidgetSpec


_OPENROUTER_CHAT = "openrouter/router/openai/v1/chat/completions"


# ---- widget overrides ---------------------------------------------------


def test_widget_overrides_no_op_for_unknown_endpoint():
    parsed = [WidgetSpec(name="prompt", kind="STRING")]
    result = apply_widget_overrides("fal-ai/some-other-model", parsed)
    assert result == parsed


def test_openrouter_chat_injects_model_combo():
    parsed = [WidgetSpec(name="prompt", kind="STRING", required=True, multiline=True)]
    result = apply_widget_overrides(_OPENROUTER_CHAT, parsed)
    by_name = {w.name: w for w in result}
    assert "model" in by_name
    model = by_name["model"]
    assert model.kind == "COMBO"
    assert model.required is True
    assert "anthropic/claude-sonnet-4.5" in model.options
    assert "google/gemini-2.5-pro" in model.options
    assert "openai/gpt-4o" in model.options


def test_openrouter_chat_injects_system_prompt():
    parsed = [WidgetSpec(name="prompt", kind="STRING", required=True, multiline=True)]
    result = apply_widget_overrides(_OPENROUTER_CHAT, parsed)
    by_name = {w.name: w for w in result}
    sp = by_name.get("system_prompt")
    assert sp is not None
    assert sp.kind == "STRING"
    assert sp.multiline is True
    assert sp.required is False


def test_openrouter_chat_preserves_existing_prompt_widget():
    """If schema-parser already produced a prompt widget, we don't clobber it."""
    parsed = [WidgetSpec(name="prompt", kind="STRING", required=True, multiline=True)]
    result = apply_widget_overrides(_OPENROUTER_CHAT, parsed)
    by_name = {w.name: w for w in result}
    assert by_name["prompt"].kind == "STRING"
    assert by_name["prompt"].required is True


def test_widget_override_replaces_same_name():
    """If both parsed-widgets and overrides define the same name, override wins."""
    parsed = [WidgetSpec(name="model", kind="STRING", default="something")]
    result = apply_widget_overrides(_OPENROUTER_CHAT, parsed)
    by_name = {w.name: w for w in result}
    # The override `model` widget is COMBO, not STRING.
    assert by_name["model"].kind == "COMBO"


# ---- payload transformer ------------------------------------------------


def test_payload_transformer_no_op_for_unknown_endpoint():
    payload = {"prompt": "hello", "model": "x"}
    result = apply_payload_transformer("fal-ai/some-other-model", payload)
    assert result == payload


def test_openrouter_chat_transform_basic():
    payload = {"prompt": "What's the weather?", "model": "anthropic/claude-sonnet-4.5"}
    result = apply_payload_transformer(_OPENROUTER_CHAT, payload)
    assert "prompt" not in result, "flat prompt must be stripped after transform"
    assert result["model"] == "anthropic/claude-sonnet-4.5"
    assert result["messages"] == [
        {"role": "user", "content": "What's the weather?"}
    ]


def test_openrouter_chat_transform_with_system_prompt():
    payload = {
        "prompt": "Translate this.",
        "system_prompt": "You are a French translator.",
        "model": "openai/gpt-4o",
    }
    result = apply_payload_transformer(_OPENROUTER_CHAT, payload)
    assert "system_prompt" not in result
    assert "prompt" not in result
    assert result["messages"] == [
        {"role": "system", "content": "You are a French translator."},
        {"role": "user", "content": "Translate this."},
    ]


def test_openrouter_chat_transform_skips_empty_system_prompt():
    payload = {"prompt": "Hi.", "system_prompt": "", "model": "x"}
    result = apply_payload_transformer(_OPENROUTER_CHAT, payload)
    # Only the user message survives; empty system prompt is dropped.
    assert result["messages"] == [{"role": "user", "content": "Hi."}]


def test_openrouter_chat_transform_skips_whitespace_only_prompts():
    payload = {"prompt": "   ", "system_prompt": "\n  \t", "model": "x"}
    result = apply_payload_transformer(_OPENROUTER_CHAT, payload)
    # Whitespace-only counts as empty; messages stays absent.
    assert "messages" not in result


def test_openrouter_chat_transform_preserves_other_keys():
    """Extra payload fields (e.g. temperature, max_tokens) survive the transform."""
    payload = {
        "prompt": "hello",
        "model": "openai/gpt-4o",
        "temperature": 0.7,
        "max_tokens": 1000,
    }
    result = apply_payload_transformer(_OPENROUTER_CHAT, payload)
    assert result["temperature"] == 0.7
    assert result["max_tokens"] == 1000


# ---- registry shape -----------------------------------------------------


def test_widget_overrides_registry_entries_are_lists_of_widgetspec():
    for endpoint_id, overrides in WIDGET_OVERRIDES.items():
        assert isinstance(overrides, list), f"{endpoint_id} overrides must be a list"
        assert all(isinstance(w, WidgetSpec) for w in overrides)


def test_payload_transformers_registry_entries_are_callable():
    for endpoint_id, fn in PAYLOAD_TRANSFORMERS.items():
        assert callable(fn), f"{endpoint_id} transformer must be callable"
