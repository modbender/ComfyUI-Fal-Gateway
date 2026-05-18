"""Curated image-to-text (vision) catalog.

Two sources feed the I2T dropdown:

1. **fal-direct vision endpoints** (Florence-2, Moondream, SA2VA, etc.)
   auto-merge from the live fal catalog via `catalogs.build_catalog`. The
   work here is filtering noise — NSFW classifiers, embeddings, OCR-only
   sub-paths, batch variants — via `HIDDEN_ENDPOINTS`.

2. **OpenRouter vision-capable LLMs** (Claude, Gemini, GPT-4o, Grok, ...)
   are NOT in fal's catalog as individual entries. We pull the full model
   list via `_openrouter_shared.load_models()` (cached, see
   `storage/openrouter.py`), filter to those whose
   `architecture.input_modalities` contains `"image"`, and synthesize one
   `CatalogEntry` per — all dispatching to the fal endpoint
   `openrouter/router/vision` with `extra_payload={"model": "<id>"}`.

Adding a new vision model = nothing required:
  - fal-direct: auto-merges from live catalog
  - OpenRouter: auto-appears next cache refresh once OpenRouter ships it
"""

from __future__ import annotations

from ..models import CatalogEntry
from ..openrouter.catalog import filter_vision_capable
from ._openrouter_shared import entry_for, load_models


_OPENROUTER_VISION_ENDPOINT = "openrouter/router/vision"


def _build_curated() -> list[CatalogEntry]:
    """Dynamically build the I2T curated list from the OpenRouter cache."""
    vision = filter_vision_capable(load_models())
    return [entry_for(m, _OPENROUTER_VISION_ENDPOINT) for m in vision]


# Module-level eval at import time so `catalogs.__init__._CATEGORY_CURATED`
# captures the resolved list. If you need to refresh after the openrouter
# cache is rewritten at runtime, call `_build_curated()` again.
CURATED: list[CatalogEntry] = _build_curated()


# Suffix-based filter for the fal-direct live merge.
#
# fal's `vision` category is a grab-bag — captioners, OCR, object detection,
# region querying, embeddings, NSFW classifiers, video. We only want the
# "describe this image as text" subset in the dropdown. Most non-caption
# endpoints follow a clear naming convention, so we filter by URL suffix
# instead of maintaining an explicit per-endpoint blacklist.
#
# When fal ships a new endpoint ending in `/embed` or `/object-detection`,
# it gets hidden automatically — no maintenance required. This is the same
# spirit as the OpenRouter dynamic catalog: encode the RULE, not the list.
HIDDEN_ENDPOINT_SUFFIXES: tuple[str, ...] = (
    "/nsfw",
    "/video",
    "/embed",
    "-embeddings",
    "/ocr",
    "/batch",
    "/batched",
    "/detect",
    "/detection",
    "-detection",
    "/point",
    "/query",
    "/visual-query",
    "-segmentation",
    "-proposal",
    "-region-caption",
    "/region-to-category",
    "/region-to-description",
)


# Endpoints to suppress that don't fit a clean suffix pattern.
# Keep this set TINY — anything that can be a suffix rule belongs above.
HIDDEN_ENDPOINTS: frozenset[str] = frozenset(
    {
        # Protocol routers (surfaced as OpenRouter curated rows, not standalone)
        "openrouter/router/vision",
        "perceptron/isaac-01/openai/v1/chat/completions",
        # OCR-only without the /ocr suffix
        "fal-ai/got-ocr/v2",
        # Florence-2 caption duplicates — keep `/detailed-caption` as canonical.
        # Both these are also caption endpoints but produce shorter/longer
        # variants; surfacing all three would clutter the dropdown.
        "fal-ai/florence-2-large/caption",
        "fal-ai/florence-2-large/more-detailed-caption",
        # Arbiter sub-variants — keep `fal-ai/arbiter/image` as canonical
        "fal-ai/arbiter/image/text",
        "fal-ai/arbiter/image/image",
        # SA2VA image endpoints require a text prompt + image (chat-style) and
        # don't fit the "describe this image" shape used by the I2T dropdown.
        "fal-ai/sa2va/4b/image",
        "fal-ai/sa2va/8b/image",
    }
)
