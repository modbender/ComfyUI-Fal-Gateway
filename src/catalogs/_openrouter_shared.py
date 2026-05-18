"""Shared OpenRouter loader + entry builder for `t2t.py` and `i2t.py`.

Both catalogs need the same flow: cache-first load with live fetch on miss,
then build `CatalogEntry` rows that route through a fal "router" endpoint
with `extra_payload={"model": "<openrouter id>"}`. The only differences
between T2T and I2T are:
  1. Which router endpoint to dispatch to (chat-completions vs vision)
  2. Which modality filter to apply on read (text-output vs image-input)

Keep this module private to `catalogs/` (leading underscore). External
callers go through `catalogs.build_catalog` / `catalogs.resolve`.
"""

from __future__ import annotations

from typing import Any

from ..models import CatalogEntry
from ..openrouter import catalog as openrouter_catalog
from ..storage import openrouter as openrouter_cache


# Provider IDs from OpenRouter that need a nicer display label. Anything not
# in here falls through to `provider.replace("-", " ").title()` — fine for
# `anthropic` → "Anthropic", `google` → "Google", `deepseek` → "Deepseek".
# This map is only for cases where Title-casing gives an ugly result.
PROVIDER_DISPLAY_OVERRIDES: dict[str, str] = {
    "x-ai": "xAI",
    "meta-llama": "Meta",
    "mistralai": "Mistral",
    "openai": "OpenAI",
    "deepseek": "DeepSeek",
}


def load_models() -> list[dict[str, Any]]:
    """Cache-first load. Falls back to live fetch (with retries) on miss
    or stale cache; writes the fresh list back to disk on success.

    Returns the FULL model list — callers filter by modality via
    `openrouter_catalog.filter_text_capable` / `filter_vision_capable`.
    """
    cached = openrouter_cache.load_if_fresh()
    if cached is not None:
        return cached
    fresh = openrouter_catalog.fetch_all_models()
    if fresh:
        openrouter_cache.write(fresh)
    return fresh


def provider_from_id(model_id: str) -> str:
    """OpenRouter IDs look like `anthropic/claude-sonnet-4.5` → `anthropic`."""
    return model_id.split("/", 1)[0] if "/" in model_id else "unknown"


def _display_provider(provider: str) -> str:
    """Apply PROVIDER_DISPLAY_OVERRIDES, falling back to Title-cased hyphens."""
    return PROVIDER_DISPLAY_OVERRIDES.get(
        provider,
        provider.replace("-", " ").title(),
    )


def entry_for(model: dict[str, Any], endpoint_id: str) -> CatalogEntry:
    """Build a CatalogEntry that routes through `endpoint_id` and injects
    the OpenRouter model_id via `extra_payload['model']`.

    Display name follows the established `[Vendor] Model Name` pattern so
    the dropdown sort key (provider, display_name) keeps related models
    grouped.
    """
    model_id = model["id"]
    provider = provider_from_id(model_id)
    display = model.get("name") or model_id
    return CatalogEntry(
        display_name=f"[{_display_provider(provider)}] {display}",
        endpoint_id=endpoint_id,
        extra_payload={"model": model_id},
        provider=provider,
        description=str(model.get("description") or ""),
    )
