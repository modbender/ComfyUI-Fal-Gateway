"""Dynamic text-to-text catalog.

fal's `llm` category is structurally awkward: most usable models live
behind OpenRouter's chat-completions router (one fal endpoint, dozens of
upstream models via a `model` parameter). Surfacing the router as a
single dropdown row forces users into a two-step decision. This module
flattens by pulling OpenRouter's full model list (via
`_openrouter_shared.load_models()`, cache-first) and synthesising one
`CatalogEntry` per text-output-capable model — all dispatching to the
fal endpoint `openrouter/router/openai/v1/chat/completions` with
`extra_payload={"model": "<openrouter id>"}`.

No hardcoded model IDs. New OpenRouter models appear automatically on
the next cache refresh; deprecated ones drop off. The right-click
"Fal-Gateway: refresh catalog cache" menu forces an immediate refetch
(see `routes.py::refresh_catalog`).

`HIDDEN_ENDPOINTS` still exists to suppress the protocol routers
themselves (chat-completions, responses) from the fal-direct merge —
their constituent models are surfaced as curated rows above, so the
routers as standalone selections would just confuse the user.
"""

from __future__ import annotations

from ..models import CatalogEntry
from ..openrouter.catalog import filter_text_capable
from ._openrouter_shared import entry_for, load_models


_OPENROUTER_CHAT_ENDPOINT = "openrouter/router/openai/v1/chat/completions"


def _build_curated() -> list[CatalogEntry]:
    """Dynamically build the T2T curated list from the OpenRouter cache."""
    text_models = filter_text_capable(load_models())
    return [entry_for(m, _OPENROUTER_CHAT_ENDPOINT) for m in text_models]


# Module-level eval at import time so `catalogs.__init__._CATEGORY_CURATED`
# captures the resolved list. Call `_build_curated()` again to rebuild after
# the openrouter cache has been refreshed at runtime.
CURATED: list[CatalogEntry] = _build_curated()


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
