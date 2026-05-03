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
# parameter. Curated as a `{display name: model id}` dict so the dropdown shows
# friendly names (e.g. "Anthropic — Claude Sonnet 4.5") while we send the raw
# OpenRouter model id (`anthropic/claude-sonnet-4.5`) to fal at submit time.
# Provider grouped, alphabetic by family. Adding a model = one entry.
_OPENROUTER_CHAT_MODELS: dict[str, str] = {
    # Anthropic
    "Anthropic — Claude Opus 4.1": "anthropic/claude-opus-4.1",
    "Anthropic — Claude Sonnet 4.5": "anthropic/claude-sonnet-4.5",
    "Anthropic — Claude Sonnet 4": "anthropic/claude-sonnet-4",
    "Anthropic — Claude 3.7 Sonnet": "anthropic/claude-3.7-sonnet",
    "Anthropic — Claude 3.5 Sonnet": "anthropic/claude-3.5-sonnet",
    "Anthropic — Claude 3.5 Haiku": "anthropic/claude-3.5-haiku",
    "Anthropic — Claude 3 Opus": "anthropic/claude-3-opus",
    "Anthropic — Claude 3 Haiku": "anthropic/claude-3-haiku",
    # Google
    "Google — Gemini 2.5 Pro": "google/gemini-2.5-pro",
    "Google — Gemini 2.5 Flash": "google/gemini-2.5-flash",
    "Google — Gemini 2.0 Flash": "google/gemini-2.0-flash-001",
    "Google — Gemini Flash 1.5": "google/gemini-flash-1.5",
    "Google — Gemini Flash 1.5 (8B)": "google/gemini-flash-1.5-8b",
    # OpenAI
    "OpenAI — GPT-5": "openai/gpt-5",
    "OpenAI — GPT-4o": "openai/gpt-4o",
    "OpenAI — GPT-4o mini": "openai/gpt-4o-mini",
    "OpenAI — o3": "openai/o3",
    "OpenAI — o1": "openai/o1",
    "OpenAI — o1 mini": "openai/o1-mini",
    # Meta
    "Meta — Llama 3.3 70B Instruct": "meta-llama/llama-3.3-70b-instruct",
    "Meta — Llama 3.1 405B Instruct": "meta-llama/llama-3.1-405b-instruct",
    "Meta — Llama 3.1 70B Instruct": "meta-llama/llama-3.1-70b-instruct",
    "Meta — Llama 3.1 8B Instruct": "meta-llama/llama-3.1-8b-instruct",
    # Mistral
    "Mistral — Large": "mistralai/mistral-large",
    "Mistral — Small": "mistralai/mistral-small",
    "Mistral — Codestral": "mistralai/codestral",
    # DeepSeek
    "DeepSeek — R1": "deepseek/deepseek-r1",
    "DeepSeek — V3": "deepseek/deepseek-v3",
    # xAI
    "xAI — Grok 3": "x-ai/grok-3",
    "xAI — Grok 3 mini": "x-ai/grok-3-mini",
    # Qwen
    "Qwen — Qwen 2.5 72B Instruct": "qwen/qwen-2.5-72b-instruct",
    "Qwen — Qwen 2.5 Coder 32B Instruct": "qwen/qwen-2.5-coder-32b-instruct",
}

_DEFAULT_OPENROUTER_DISPLAY = "Anthropic — Claude Sonnet 4.5"


def _openrouter_model_widget() -> WidgetSpec:
    """Curated COMBO showing friendly names; widget value is the display name,
    payload-side mapping happens in the per-endpoint transformer."""
    return WidgetSpec(
        name="model",
        kind="COMBO",
        default=_DEFAULT_OPENROUTER_DISPLAY,
        options=list(_OPENROUTER_CHAT_MODELS.keys()),
        required=True,
        payload_key="model",
    )


def _system_prompt_widget(name: str = "system_prompt") -> WidgetSpec:
    return WidgetSpec(
        name=name,
        kind="STRING",
        default="",
        required=False,
        multiline=True,
        payload_key=name,  # mapped away by the transformer; UI-only key
    )


_OPENROUTER_CHAT_OVERRIDES = [_openrouter_model_widget(), _system_prompt_widget()]
_OPENROUTER_RESPONSES_OVERRIDES = [_openrouter_model_widget(), _system_prompt_widget()]


def _resolve_openrouter_model(value: Any) -> str | None:
    """Map a user-facing display name back to its OpenRouter model id.

    Tolerates legacy raw-id values from saved workflows that pre-date the
    display-name dropdown (returns the value unchanged if it's already a
    raw id like `anthropic/claude-sonnet-4.5`).
    """
    if not isinstance(value, str) or not value:
        return None
    mapped = _OPENROUTER_CHAT_MODELS.get(value)
    if mapped is not None:
        return mapped
    # Backward-compat: if `value` matches a raw id from the dict's values, keep it.
    if value in _OPENROUTER_CHAT_MODELS.values():
        return value
    return value  # unknown — pass through, fal will reject at submit time


def _openrouter_chat_transform(payload: dict[str, Any]) -> dict[str, Any]:
    """Translate `{prompt, model, system_prompt}` → OpenAI chat-completions shape:
    `{model, messages: [{role: system, content}, {role: user, content}]}`.
    Empty/missing prompts skipped so we never send empty messages.
    """
    out = dict(payload)
    sys_p = out.pop("system_prompt", None)
    user_p = out.pop("prompt", None)
    out["model"] = _resolve_openrouter_model(out.get("model")) or out.get("model")
    messages: list[dict[str, str]] = []
    if isinstance(sys_p, str) and sys_p.strip():
        messages.append({"role": "system", "content": sys_p})
    if isinstance(user_p, str) and user_p.strip():
        messages.append({"role": "user", "content": user_p})
    if messages:
        out["messages"] = messages
    return out


def _openrouter_responses_transform(payload: dict[str, Any]) -> dict[str, Any]:
    """Translate `{prompt, model, system_prompt}` → OpenAI Responses API shape:
    `{model, input: <user>, instructions?: <system>}`.

    Empty/whitespace-only system_prompt drops the instructions field. fal's
    Responses endpoint rejects payloads that don't follow this contract with
    `invalid_prompt`; the previous chat-completions transformer was wrong here.
    """
    out = dict(payload)
    sys_p = out.pop("system_prompt", None)
    user_p = out.pop("prompt", None)
    out["model"] = _resolve_openrouter_model(out.get("model")) or out.get("model")
    if isinstance(user_p, str) and user_p.strip():
        out["input"] = user_p
    if isinstance(sys_p, str) and sys_p.strip():
        out["instructions"] = sys_p
    return out


WIDGET_OVERRIDES: dict[str, list[WidgetSpec]] = {
    "openrouter/router/openai/v1/chat/completions": _OPENROUTER_CHAT_OVERRIDES,
    "openrouter/router/openai/v1/responses": _OPENROUTER_RESPONSES_OVERRIDES,
}

PAYLOAD_TRANSFORMERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "openrouter/router/openai/v1/chat/completions": _openrouter_chat_transform,
    "openrouter/router/openai/v1/responses": _openrouter_responses_transform,
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
