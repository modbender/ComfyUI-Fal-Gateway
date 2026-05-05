"""Per-endpoint payload customisations.

Single registry — `PAYLOAD_TRANSFORMERS` — maps a fal endpoint id to a
function that reshapes the assembled request payload to the endpoint's
contract before submission.

OpenRouter chat-completions and responses are protocol-level routers
that take an OpenAI-shaped body. The user-facing model selection is
NOT a widget anymore — it's a row in the curated T2T catalog
(`src/catalogs/t2t.py`) that injects `extra_payload={"model": "..."}`
into the request before the transformer runs. The transformer only
needs to wrap `{prompt, system_prompt}` into the right shape for the
endpoint:

  - chat-completions: `{model, messages: [{role: system, content},
    {role: user, content}]}`
  - responses:        `{model, input, instructions?}`

Adding a new endpoint customisation = one entry in `PAYLOAD_TRANSFORMERS`.
"""

from __future__ import annotations

from typing import Any, Callable


def _openrouter_chat_transform(payload: dict[str, Any]) -> dict[str, Any]:
    """Wrap `{prompt, system_prompt, model, ...}` into chat-completions shape.

    Result: `{model, messages: [...]}`. Empty/missing prompts are skipped so
    we never send empty messages. The `model` field is expected to already
    hold a raw OpenRouter model id (catalog entry's extra_payload provides it).
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


def _openrouter_responses_transform(payload: dict[str, Any]) -> dict[str, Any]:
    """Wrap `{prompt, system_prompt, model, ...}` into the Responses API shape.

    Result: `{model, input: <user>, instructions?: <system>}`. fal's Responses
    endpoint rejects payloads that don't follow this contract with
    `invalid_prompt`. Empty/whitespace-only system_prompt drops the
    `instructions` field.
    """
    out = dict(payload)
    sys_p = out.pop("system_prompt", None)
    user_p = out.pop("prompt", None)
    if isinstance(user_p, str) and user_p.strip():
        out["input"] = user_p
    if isinstance(sys_p, str) and sys_p.strip():
        out["instructions"] = sys_p
    return out


PAYLOAD_TRANSFORMERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "openrouter/router/openai/v1/chat/completions": _openrouter_chat_transform,
    "openrouter/router/openai/v1/responses": _openrouter_responses_transform,
}


def apply_payload_transformer(
    endpoint_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Run the registered payload transformer for `endpoint_id`, if any."""
    transformer = PAYLOAD_TRANSFORMERS.get(endpoint_id)
    if transformer is None:
        return payload
    return transformer(payload)
