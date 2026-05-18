"""Curated user-facing catalogs for categories where fal's live `llm` /
`vision` listings are structurally awkward.

The flat catalogs surface ONE row per model the user can pick, hiding the
"protocol router vs direct endpoint" implementation detail. OpenRouter's
chat-completions endpoint, which exposes 30+ upstream models via a `model`
parameter, becomes 30 explicit rows; direct LLM endpoints (Bytedance Seed,
Nemotron, etc.) become 1 row each.

Each per-category registry exports:
- `CURATED`: list[CatalogEntry] — hand-curated rows
- `HIDDEN_ENDPOINTS`: frozenset[str] — fal endpoints to drop from the live
  merge (typically the protocol routers whose models we've enumerated above)

This module's `build_catalog(category, live)` performs the merge: curated
first, then live entries that aren't hidden, sorted by (provider, name).
"""

from __future__ import annotations

from typing import Iterable

from ..model_registry import extract_provider
from ..models import CatalogEntry
from ..widget_spec import ModelEntry
from . import i2t, t2t


# Maps category → module that exports the dynamic `CURATED` list. Looked up
# at CALL time, not import time — `t2t.CURATED` and `i2t.CURATED` are rebuilt
# whenever someone calls `_build_curated()` after the openrouter cache refreshes,
# so we must dereference fresh on every catalog build (otherwise tests that
# patch `t2t.CURATED` would see stale captured references).
_CATEGORY_MODULES = {"llm": t2t, "vision": i2t}


def _curated_for(category: str) -> list[CatalogEntry]:
    """Resolve the CURATED list for a category at call time."""
    mod = _CATEGORY_MODULES.get(category)
    return mod.CURATED if mod is not None else []


def _hidden_for(category: str) -> frozenset[str]:
    mod = _CATEGORY_MODULES.get(category)
    return mod.HIDDEN_ENDPOINTS if mod is not None else frozenset()


def _hidden_suffixes_for(category: str) -> tuple[str, ...]:
    mod = _CATEGORY_MODULES.get(category)
    return getattr(mod, "HIDDEN_ENDPOINT_SUFFIXES", ()) if mod is not None else ()


def has_curated_catalog(category: str) -> bool:
    """True if the category uses a flat curated catalog instead of the
    live `model_registry.list_display_strings` dropdown."""
    return category in _CATEGORY_MODULES


def build_catalog(
    category: str,
    live: Iterable[ModelEntry],
) -> list[CatalogEntry]:
    """Merge curated + live entries for a category.

    Curated entries win: any live endpoint already covered by a curated
    row (same endpoint_id with NO extra_payload) is skipped. Endpoints in
    the category's HIDDEN set are always skipped. Live entries not in the
    HIDDEN set get auto-wrapped as 1:1 CatalogEntry rows with
    provider-prefixed display names.

    Sorted by (provider, display_name) so the UI clusters by provider.
    """
    curated = _curated_for(category)
    hidden = _hidden_for(category)
    hidden_suffixes = _hidden_suffixes_for(category)

    out: list[CatalogEntry] = list(curated)
    # Endpoints already covered by a curated row WITHOUT extra_payload —
    # we don't want to also auto-wrap them as a separate live row.
    direct_curated = {
        e.endpoint_id for e in curated if not e.extra_payload
    }

    for entry in live:
        if entry.id in hidden or entry.id in direct_curated:
            continue
        if hidden_suffixes and entry.id.endswith(hidden_suffixes):
            continue
        provider = extract_provider(entry.id) or "unknown"
        out.append(
            CatalogEntry(
                display_name=f"[{provider}] {entry.display_name}",
                endpoint_id=entry.id,
                provider=provider,
                description=entry.description,
            )
        )

    return sorted(out, key=lambda e: (e.provider.lower(), e.display_name.lower()))


def list_display_names(
    category: str,
    live: Iterable[ModelEntry],
) -> list[str]:
    """Return just the user-facing strings — the values that go into the
    COMBO widget options."""
    return [e.display_name for e in build_catalog(category, live)]


def resolve(category: str, display_name: str, live: Iterable[ModelEntry]) -> CatalogEntry | None:
    """Reverse lookup: display string → CatalogEntry. Returns None if
    `display_name` isn't in the category's catalog."""
    for entry in build_catalog(category, live):
        if entry.display_name == display_name:
            return entry
    return None
