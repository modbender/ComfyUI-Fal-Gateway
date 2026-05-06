"""Curated image-to-text (vision) catalog.

Two sources feed the I2T dropdown:

1. **fal-direct vision endpoints** (Florence-2, Moondream, SA2VA, etc.)
   auto-merge from the live fal catalog via `catalogs.build_catalog`. The
   work here is filtering noise — NSFW classifiers, embeddings, OCR-only
   sub-paths, batch variants — via `HIDDEN_ENDPOINTS`.

2. **OpenRouter vision-capable LLMs** (Claude, Gemini, GPT-4o, Grok, ...)
   are NOT in fal's catalog as individual entries. We pull the list from
   OpenRouter's own `/api/v1/models` endpoint (cached, see
   `storage/openrouter.py`), filter to those whose
   `architecture.input_modalities` contains `"image"`, and synthesize one
   `CatalogEntry` per — all dispatching to the fal endpoint
   `openrouter/router/vision` with `extra_payload={"model": "<id>"}`.

Adding a new vision model = nothing required:
  - fal-direct: auto-merges from live catalog
  - OpenRouter: auto-appears next cache refresh once OpenRouter ships it
"""

from __future__ import annotations

from typing import Any

from ..models import CatalogEntry
from ..openrouter import catalog as openrouter_catalog
from ..storage import openrouter as openrouter_cache


_OPENROUTER_VISION_ENDPOINT = "openrouter/router/vision"


def _load_openrouter_models() -> list[dict[str, Any]]:
    """Cache-first load with live fetch on miss/stale."""
    cached = openrouter_cache.load_if_fresh()
    if cached is not None:
        return cached
    fresh = openrouter_catalog.fetch_vision_models()
    if fresh:
        openrouter_cache.write(fresh)
    return fresh


def _provider_from_id(model_id: str) -> str:
    """OpenRouter ids look like 'anthropic/claude-sonnet-4.5' → 'anthropic'."""
    return model_id.split("/", 1)[0] if "/" in model_id else "unknown"


def _entry_for(model: dict[str, Any]) -> CatalogEntry:
    model_id = model["id"]
    provider = _provider_from_id(model_id)
    display = model.get("name") or model_id
    bracket_provider = provider.replace("-", " ").title()
    return CatalogEntry(
        display_name=f"[{bracket_provider}] {display}",
        endpoint_id=_OPENROUTER_VISION_ENDPOINT,
        extra_payload={"model": model_id},
        provider=provider,
        description=str(model.get("description") or ""),
    )


def _build_curated() -> list[CatalogEntry]:
    """Dynamically build the I2T curated list from the OpenRouter cache."""
    models = _load_openrouter_models()
    # Defensive filter: even if the fetcher pre-filters, re-check here so
    # a stale cache never surfaces a text-only model in I2T.
    vision = [m for m in models if "image" in (m.get("input_modalities") or [])]
    return [_entry_for(m) for m in vision]


# Module-level eval at import time so `catalogs.__init__._CATEGORY_CURATED`
# captures the resolved list. If you need to refresh after the openrouter
# cache is rewritten at runtime, call `_build_curated()` again.
CURATED: list[CatalogEntry] = _build_curated()


# Endpoints to suppress from the live merge:
#   - Protocol routers / chat-completions wrappers (parents not used directly)
#   - Classifiers (NSFW filters)
#   - Embedding / OCR / detection sub-paths (not text-generation)
#   - Batch variants (intended for batch_input arrays, not a single image)
#   - Video sub-paths (we only handle still-image input on I2T)
#   - Florence-2 / Moondream variants we don't keep
HIDDEN_ENDPOINTS: frozenset[str] = frozenset(
    {
        # Protocol parents
        "openrouter/router/vision",  # surfaced via curated rows above
        "perceptron/isaac-01/openai/v1/chat/completions",
        # NSFW classifiers (binary; not "describe this image")
        "fal-ai/imageutils/nsfw",
        "fal-ai/x-ailab/nsfw",
        # Video-only sub-paths
        "fal-ai/video-understanding",
        "fal-ai/sa2va/4b/video",
        "fal-ai/sa2va/8b/video",
        # Embeddings
        "fal-ai/sam-3/image/embed",
        # OCR-specific (keep general caption models for general use)
        "fal-ai/got-ocr/v2",
        "fal-ai/florence-2-large/ocr",
        # Batch variants
        "fal-ai/moondream-next/batch",
        "fal-ai/moondream/batched",
        # Detection / region / pointing — non-caption-shaped
        "fal-ai/moondream3-preview/detect",
        "fal-ai/moondream3-preview/point",
        "fal-ai/moondream3-preview/query",
        "fal-ai/moondream2/object-detection",
        "fal-ai/moondream2/point-object-detection",
        "fal-ai/moondream2/visual-query",
        "fal-ai/florence-2-large/region-to-category",
        "fal-ai/florence-2-large/region-to-description",
        # Florence-2 duplicates (keep `/detailed-caption` as canonical)
        "fal-ai/florence-2-large/caption",
        "fal-ai/florence-2-large/more-detailed-caption",
        # Arbiter sub-variants (keep `fal-ai/arbiter/image` as canonical)
        "fal-ai/arbiter/image/text",
        "fal-ai/arbiter/image/image",
    }
)
