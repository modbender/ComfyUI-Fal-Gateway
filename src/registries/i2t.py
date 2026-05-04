"""Curated image-to-text (vision) catalog.

Filled in by K2 after live verification of fal's `vision` category. For
now: empty curated list + empty hidden set, so I2T behaves identically
to before — the live merge surfaces every fal vision endpoint with its
default `[provider] DisplayName` formatting.
"""

from __future__ import annotations

from ..api_models import CatalogEntry


CURATED: list[CatalogEntry] = []

HIDDEN_ENDPOINTS: frozenset[str] = frozenset()
