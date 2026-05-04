"""Curated text-to-text catalog.

fal's `llm` category is structurally awkward: most usable models live
behind OpenRouter's chat-completions router (one fal endpoint, dozens of
upstream models via a `model` parameter). Surfacing the router as a
single dropdown row forces users into a two-step decision. This registry
flattens by enumerating every OpenRouter model we want to expose as its
own row, plus any direct fal LLM endpoints we want to feature.

Adding a model = one entry in `CURATED`. Adding a direct fal LLM (e.g.
Bytedance Seed, Nemotron) is unnecessary — they're auto-merged from the
live fal catalog by `registries.build_catalog` UNLESS their endpoint_id
appears in `HIDDEN_ENDPOINTS`.

`HIDDEN_ENDPOINTS` exists to suppress the protocol routers themselves
(chat-completions, responses) from the dropdown — their constituent
models are surfaced as curated rows above, so the routers as standalone
selections would just confuse the user.
"""

from __future__ import annotations

from ..api_models import CatalogEntry


_OPENROUTER_CHAT = "openrouter/router/openai/v1/chat/completions"


def _openrouter(display: str, model_id: str, provider: str) -> CatalogEntry:
    """One curated row that routes through OpenRouter chat-completions."""
    return CatalogEntry(
        display_name=display,
        endpoint_id=_OPENROUTER_CHAT,
        extra_payload={"model": model_id},
        provider=provider,
    )


CURATED: list[CatalogEntry] = [
    # Anthropic
    _openrouter("[Anthropic] Claude Opus 4.1", "anthropic/claude-opus-4.1", "anthropic"),
    _openrouter("[Anthropic] Claude Sonnet 4.5", "anthropic/claude-sonnet-4.5", "anthropic"),
    _openrouter("[Anthropic] Claude Sonnet 4", "anthropic/claude-sonnet-4", "anthropic"),
    _openrouter("[Anthropic] Claude 3.7 Sonnet", "anthropic/claude-3.7-sonnet", "anthropic"),
    _openrouter("[Anthropic] Claude 3.5 Sonnet", "anthropic/claude-3.5-sonnet", "anthropic"),
    _openrouter("[Anthropic] Claude 3.5 Haiku", "anthropic/claude-3.5-haiku", "anthropic"),
    _openrouter("[Anthropic] Claude 3 Opus", "anthropic/claude-3-opus", "anthropic"),
    _openrouter("[Anthropic] Claude 3 Haiku", "anthropic/claude-3-haiku", "anthropic"),
    # DeepSeek
    _openrouter("[DeepSeek] R1", "deepseek/deepseek-r1", "deepseek"),
    _openrouter("[DeepSeek] V3", "deepseek/deepseek-v3", "deepseek"),
    # Google
    _openrouter("[Google] Gemini 2.5 Pro", "google/gemini-2.5-pro", "google"),
    _openrouter("[Google] Gemini 2.5 Flash", "google/gemini-2.5-flash", "google"),
    _openrouter("[Google] Gemini 2.0 Flash", "google/gemini-2.0-flash-001", "google"),
    _openrouter("[Google] Gemini Flash 1.5", "google/gemini-flash-1.5", "google"),
    _openrouter("[Google] Gemini Flash 1.5 (8B)", "google/gemini-flash-1.5-8b", "google"),
    # Meta
    _openrouter("[Meta] Llama 3.3 70B Instruct", "meta-llama/llama-3.3-70b-instruct", "meta"),
    _openrouter("[Meta] Llama 3.1 405B Instruct", "meta-llama/llama-3.1-405b-instruct", "meta"),
    _openrouter("[Meta] Llama 3.1 70B Instruct", "meta-llama/llama-3.1-70b-instruct", "meta"),
    _openrouter("[Meta] Llama 3.1 8B Instruct", "meta-llama/llama-3.1-8b-instruct", "meta"),
    # Mistral
    _openrouter("[Mistral] Large", "mistralai/mistral-large", "mistral"),
    _openrouter("[Mistral] Small", "mistralai/mistral-small", "mistral"),
    _openrouter("[Mistral] Codestral", "mistralai/codestral", "mistral"),
    # OpenAI
    _openrouter("[OpenAI] GPT-5", "openai/gpt-5", "openai"),
    _openrouter("[OpenAI] GPT-4o", "openai/gpt-4o", "openai"),
    _openrouter("[OpenAI] GPT-4o mini", "openai/gpt-4o-mini", "openai"),
    _openrouter("[OpenAI] o3", "openai/o3", "openai"),
    _openrouter("[OpenAI] o1", "openai/o1", "openai"),
    _openrouter("[OpenAI] o1 mini", "openai/o1-mini", "openai"),
    # Qwen
    _openrouter("[Qwen] Qwen 2.5 72B Instruct", "qwen/qwen-2.5-72b-instruct", "qwen"),
    _openrouter("[Qwen] Qwen 2.5 Coder 32B Instruct", "qwen/qwen-2.5-coder-32b-instruct", "qwen"),
    # xAI
    _openrouter("[xAI] Grok 3", "x-ai/grok-3", "xai"),
    _openrouter("[xAI] Grok 3 mini", "x-ai/grok-3-mini", "xai"),
]


# Endpoints to suppress from the live merge:
#   - openrouter/router          : bare router parent (no usable inference)
#   - chat/completions           : router whose models are enumerated above
#   - responses                  : alternate-protocol router; chat-completions
#                                  covers the same models, so we hide it too
HIDDEN_ENDPOINTS: frozenset[str] = frozenset(
    {
        "openrouter/router",
        "openrouter/router/openai/v1/chat/completions",
        "openrouter/router/openai/v1/responses",
    }
)
