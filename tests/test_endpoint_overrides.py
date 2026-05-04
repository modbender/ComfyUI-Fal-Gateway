"""Tests for src.endpoint_overrides — payload-shape transformers.

After K1, widget-level OpenRouter model selection moved to the curated
T2T catalog (`src/registries/t2t.py`). The endpoint_overrides module now
only houses payload transformers that reshape `{prompt, system_prompt,
model}` into the right wire format per fal endpoint.
"""

from __future__ import annotations

from src.endpoint_overrides import (
    PAYLOAD_TRANSFORMERS,
    apply_payload_transformer,
    apply_widget_overrides,
)
from src.widget_spec import WidgetSpec


_OPENROUTER_CHAT = "openrouter/router/openai/v1/chat/completions"
_OPENROUTER_RESPONSES = "openrouter/router/openai/v1/responses"


# ---- payload transformer: chat-completions ------------------------------


def test_payload_transformer_no_op_for_unknown_endpoint():
    payload = {"prompt": "hello", "model": "anthropic/claude-3.5-sonnet"}
    result = apply_payload_transformer("fal-ai/some-other-model", payload)
    assert result == payload


def test_openrouter_chat_transform_basic():
    """Catalog injects raw model id; transformer just wraps prompt → messages."""
    payload = {
        "prompt": "What's the weather?",
        "model": "anthropic/claude-sonnet-4.5",
    }
    result = apply_payload_transformer(_OPENROUTER_CHAT, payload)
    assert "prompt" not in result
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
    assert result["messages"] == [{"role": "user", "content": "Hi."}]


def test_openrouter_chat_transform_skips_whitespace_only_prompts():
    payload = {"prompt": "   ", "system_prompt": "\n  \t", "model": "x"}
    result = apply_payload_transformer(_OPENROUTER_CHAT, payload)
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


# ---- payload transformer: responses -------------------------------------


def test_openrouter_responses_transform_uses_input_not_messages():
    """Responses API takes `{model, input, instructions?}`, NOT chat-completions
    `{model, messages: [...]}`."""
    payload = {
        "prompt": "Summarise the news.",
        "model": "google/gemini-2.5-pro",
    }
    result = apply_payload_transformer(_OPENROUTER_RESPONSES, payload)
    assert "prompt" not in result
    assert "messages" not in result
    assert result["input"] == "Summarise the news."
    assert result["model"] == "google/gemini-2.5-pro"


def test_openrouter_responses_transform_maps_system_prompt_to_instructions():
    payload = {
        "prompt": "Translate.",
        "system_prompt": "You are a translator.",
        "model": "anthropic/claude-sonnet-4.5",
    }
    result = apply_payload_transformer(_OPENROUTER_RESPONSES, payload)
    assert result["instructions"] == "You are a translator."
    assert result["input"] == "Translate."
    assert "system_prompt" not in result
    assert "messages" not in result


def test_openrouter_responses_transform_skips_empty_instructions():
    payload = {"prompt": "Hi.", "system_prompt": "", "model": "openai/gpt-4o"}
    result = apply_payload_transformer(_OPENROUTER_RESPONSES, payload)
    assert "instructions" not in result
    assert result["input"] == "Hi."


# ---- widget overrides: deprecated, no-op ------------------------------


def test_apply_widget_overrides_is_no_op_after_k1():
    """Widget-level model selection moved to the T2T catalog. The shim
    exists for API compatibility with model_registry._entry_from_raw."""
    parsed = [WidgetSpec(name="prompt", kind="STRING")]
    result = apply_widget_overrides(_OPENROUTER_CHAT, parsed)
    assert result == parsed


# ---- registry shape -----------------------------------------------------


def test_payload_transformers_registry_entries_are_callable():
    for endpoint_id, fn in PAYLOAD_TRANSFORMERS.items():
        assert callable(fn), f"{endpoint_id} transformer must be callable"


def test_payload_transformers_registry_covers_both_openrouter_endpoints():
    assert _OPENROUTER_CHAT in PAYLOAD_TRANSFORMERS
    assert _OPENROUTER_RESPONSES in PAYLOAD_TRANSFORMERS
