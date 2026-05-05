"""Curated image-to-text (vision) catalog.

Unlike T2T, fal's vision category is mostly direct (one endpoint = one
model) — no protocol-router layer that needs flattening. The work here is
filtering the noise: NSFW classifiers, embeddings, OCR-specific paths,
batch variants, and per-task sub-endpoints (region-to-category,
object-detection, etc.) get hidden so the dropdown stays focused on
"point at an image, get a caption / answer" models.

Adding a new vision LLM = nothing required (auto-merges via the live
fal catalog with `[provider] DisplayName` formatting). Hiding noise =
one entry in `HIDDEN_ENDPOINTS`.
"""

from __future__ import annotations

from ..models import CatalogEntry


CURATED: list[CatalogEntry] = []


# Endpoints to suppress from the live merge:
#   - Protocol routers / chat-completions wrappers (parents not used directly)
#   - Classifiers (NSFW filters)
#   - Embedding / OCR / detection sub-paths (not text-generation)
#   - Batch variants (intended for batch_input arrays, not a single image)
#   - Video sub-paths (we only handle still-image input on I2T)
#   - Florence-2 variants we don't keep — only `detailed-caption` is kept
#     as the canonical Florence option (others are region/OCR-specialised)
#   - Moondream variants we don't keep — only the canonical caption paths
HIDDEN_ENDPOINTS: frozenset[str] = frozenset(
    {
        # Protocol parents
        "openrouter/router/vision",
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
