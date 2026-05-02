"""Per-endpoint customisations that can't be derived from fal's OpenAPI alone.

Two registries — adding a new override = one entry per registry:

  WIDGET_OVERRIDES: extra/replacement WidgetSpecs to inject after schema parsing.
                    Useful when fal's OpenAPI omits a parameter (e.g. OpenRouter's
                    `model` aggregator field) or when we want a curated dropdown
                    instead of a free-string field.

  PAYLOAD_TRANSFORMERS: post-process the assembled payload to match the endpoint's
                        actual contract. E.g. OpenAI-compatible chat-completions
                        endpoints take `messages: [{role, content}]`, not a flat
                        `prompt` — the transformer rewrites the payload accordingly.

Both are applied at well-defined seams: WIDGET_OVERRIDES inside `_entry_from_raw`
in the registry build pass; PAYLOAD_TRANSFORMERS in `_build_payload` after the
parsed widgets have produced the raw payload.
"""

from __future__ import annotations

from typing import Any, Callable

from .widget_spec import WidgetSpec


# OpenRouter aggregates 100+ chat models behind one fal endpoint via a `model`
# parameter. Curated list — bump as fal/OpenRouter add models.
# Provider grouped, alphabetic by family.
_OPENROUTER_CHAT_MODELS = [
    # Anthropic
    "anthropic/claude-opus-4.1",
    "anthropic/claude-sonnet-4.5",
    "anthropic/claude-sonnet-4",
    "anthropic/claude-3.7-sonnet",
    "anthropic/claude-3.5-sonnet",
    "anthropic/claude-3.5-haiku",
    "anthropic/claude-3-opus",
    "anthropic/claude-3-haiku",
    # Google
    "google/gemini-2.5-pro",
    "google/gemini-2.5-flash",
    "google/gemini-2.0-flash-001",
    "google/gemini-flash-1.5",
    "google/gemini-flash-1.5-8b",
    # OpenAI
    "openai/gpt-5",
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
    "openai/o3",
    "openai/o1",
    "openai/o1-mini",
    # Meta
    "meta-llama/llama-3.3-70b-instruct",
    "meta-llama/llama-3.1-405b-instruct",
    "meta-llama/llama-3.1-70b-instruct",
    "meta-llama/llama-3.1-8b-instruct",
    # Mistral
    "mistralai/mistral-large",
    "mistralai/mistral-small",
    "mistralai/codestral",
    # DeepSeek
    "deepseek/deepseek-r1",
    "deepseek/deepseek-v3",
    # xAI
    "x-ai/grok-3",
    "x-ai/grok-3-mini",
    # Qwen
    "qwen/qwen-2.5-72b-instruct",
    "qwen/qwen-2.5-coder-32b-instruct",
]


_OPENROUTER_CHAT_OVERRIDES = [
    WidgetSpec(
        name="model",
        kind="COMBO",
        default="anthropic/claude-sonnet-4.5",
        options=list(_OPENROUTER_CHAT_MODELS),
        required=True,
        payload_key="model",
    ),
    WidgetSpec(
        name="system_prompt",
        kind="STRING",
        default="",
        required=False,
        multiline=True,
        # Mapped away by `_openrouter_chat_transform`; stays a UI-level field only.
        payload_key="system_prompt",
    ),
]


def _openrouter_chat_transform(payload: dict[str, Any]) -> dict[str, Any]:
    """Translate `{prompt, model, system_prompt}` → OpenAI chat-completions shape.

    Result: `{model, messages: [{role: system, content: ...}, {role: user, content: ...}]}`.
    Empty / missing prompts are skipped so we never send empty messages.
    """
    out = dict(payload)
    sys_p = out.pop("system_prompt", None)
    user_p = out.pop("prompt", None)
    messages: list[dict[str, str]] = []
    if isinstance(sys_p, str) and sys_p.strip():
        messages.append({"role": "system", "content": sys_p})
    if isinstance(user_p, str) and user_p.strip():
        messages.append({"role": "user", "content": user_p})
    if messages:
        out["messages"] = messages
    return out


WIDGET_OVERRIDES: dict[str, list[WidgetSpec]] = {
    "openrouter/router/openai/v1/chat/completions": _OPENROUTER_CHAT_OVERRIDES,
}

PAYLOAD_TRANSFORMERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "openrouter/router/openai/v1/chat/completions": _openrouter_chat_transform,
}


def apply_widget_overrides(
    endpoint_id: str, widgets: list[WidgetSpec]
) -> list[WidgetSpec]:
    """Merge override widgets into the parsed list, replacing same-named widgets.

    Overrides win when their name matches an existing widget; non-overlapping
    override entries are appended at the end.
    """
    overrides = WIDGET_OVERRIDES.get(endpoint_id)
    if not overrides:
        return widgets
    by_name: dict[str, WidgetSpec] = {w.name: w for w in widgets}
    for ow in overrides:
        by_name[ow.name] = ow
    return list(by_name.values())


def apply_payload_transformer(
    endpoint_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Run the registered payload transformer for `endpoint_id`, if any."""
    transformer = PAYLOAD_TRANSFORMERS.get(endpoint_id)
    if transformer is None:
        return payload
    return transformer(payload)
