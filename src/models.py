"""Pydantic models for boundary I/O + user-facing catalog rows.

This module owns every Pydantic model the package uses:

  - **fal API parsing** — `PriceEntry`, `PricingPage` for `/v1/models/pricing`
    responses. Field aliases tolerate fal's variant key names without manual
    try/except.
  - **Cache file I/O** — `PricingCacheFile`, `CatalogCacheFile` for the JSON
    files we read/write under `cache/`. Replaces hand-rolled load/save with
    `model_validate_json` + `model_dump_json`.
  - **HTTP response shapes** — typed envelopes for the four routes in
    `server_routes.py`. The frontend wire format is unchanged.
  - **Catalog rows** — `CatalogEntry` for T2T/I2T flat dropdowns
    (`src/catalogs/`).

Internal domain objects that don't need runtime validation (`WidgetSpec`,
`ModelEntry`) stay as plain dataclasses in `widget_spec.py`.

Model conventions follow ComfyUI's own `comfy_api_nodes/apis/*.py`: plain
`pydantic.BaseModel` subclasses, `Field(default, description=..., ge=...)`,
modern `int | None` typing.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


# =====================================================================
# fal API: /v1/models/pricing
# =====================================================================


class PriceEntry(BaseModel):
    """One pricing record from fal's pricing endpoint.

    fal sometimes returns variant key names (`unit_price` vs `price`,
    `unit` vs `pricing_unit`); `validation_alias=AliasChoices(...)`
    accepts both on input. Output always uses the canonical names.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    endpoint_id: str = Field(
        validation_alias=AliasChoices("endpoint_id", "id"),
        description="fal endpoint id, e.g. 'fal-ai/flux/dev'",
    )
    unit_price: float | None = Field(
        default=None,
        validation_alias=AliasChoices("unit_price", "price"),
        description="Price per unit in `currency`. None when fal didn't return a value.",
    )
    unit: str | None = Field(
        default=None,
        validation_alias=AliasChoices("unit", "pricing_unit"),
        description="'image', 'second', 'megapixels', '1m_tokens', etc.",
    )
    currency: str | None = Field(
        default="USD",
        description="ISO 4217 currency code; defaults to USD when fal omits it.",
    )


class PricingPage(BaseModel):
    """A page of pricing data — pricing endpoint envelope.

    fal has been observed using `prices`, `models`, or `data` as the list
    key; we accept all three on input.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    prices: list[PriceEntry] = Field(
        default_factory=list,
        validation_alias=AliasChoices("prices", "models", "data"),
    )
    next_cursor: str | None = None
    has_more: bool = False


# =====================================================================
# Cache files (cache/pricing.json, cache/catalog.json)
# =====================================================================


class PricingCacheFile(BaseModel):
    """Schema for `cache/pricing.json`."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int
    fetched_at: str = Field(description="ISO 8601 timestamp of last successful fetch.")
    prices: dict[str, dict[str, Any]] = Field(default_factory=dict)
    no_pricing: list[str] = Field(
        default_factory=list,
        description="Endpoint ids fal's pricing index doesn't recognise; skipped on subsequent sweeps.",
    )


class CatalogCacheFile(BaseModel):
    """Schema for `cache/catalog.json`."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int
    fetched_at: str = Field(description="ISO 8601 timestamp of last successful fetch.")
    models: list[dict[str, Any]] = Field(default_factory=list)


# =====================================================================
# HTTP response envelopes
# =====================================================================


class ErrorResponse(BaseModel):
    ok: Literal[False] = False
    error: str


class SchemaResponse(BaseModel):
    """`GET /fal_gateway/schema/{model_id_b64}` success body."""

    ok: Literal[True] = True
    model_id: str
    display_name: str
    category: str
    shape: str
    widgets: list[dict[str, Any]]
    unit_price: float | None = None
    unit: str | None = None
    currency: str | None = None


class RefreshResponse(BaseModel):
    """`POST /fal_gateway/refresh` success body."""

    ok: Literal[True] = True
    deleted: bool
    message: str


class HealthResponse(BaseModel):
    """`GET /fal_gateway/health` body (no `ok` envelope; pure diagnostic)."""

    fal_key_present: bool
    model_count: int


class PricingRefreshResponse(BaseModel):
    """`POST /fal_gateway/pricing_refresh` success body."""

    ok: Literal[True] = True
    started: bool
    message: str


# =====================================================================
# User-facing model dropdown rows (T2T, I2T, …)
# =====================================================================


class CatalogEntry(BaseModel):
    """A row in a user-facing model dropdown.

    Decouples *what the user picks* from *which fal endpoint we actually
    call*: one fal endpoint can surface as many rows (e.g. OpenRouter's
    chat-completions router exposes dozens of upstream models via a
    `model` parameter), or 1 fal endpoint = 1 row for direct models.

    `extra_payload` merges into the assembled fal request before any
    endpoint-specific transformer runs. This is how we inject
    `{"model": "anthropic/claude-sonnet-4.5"}` for an OpenRouter row
    without surfacing a separate `model` widget on the node.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(
        description="Friendly string shown in the COMBO and stored in saved workflows."
    )
    endpoint_id: str = Field(
        description="The real fal endpoint id this entry calls."
    )
    extra_payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Fields merged into the request payload before transform.",
    )
    provider: str = Field(
        description="Provider name (e.g. 'anthropic', 'fal-ai') for sorting + grouping.",
    )
    description: str = Field(default="", description="Optional row tooltip.")
