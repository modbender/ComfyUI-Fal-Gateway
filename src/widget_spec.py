"""WidgetSpec — wire format describing a single fal model parameter.

A list of WidgetSpec describes one model's full parameter set. The frontend
renders widgets/sockets from the list; the backend filters incoming kwargs
against the same list before constructing the fal payload. Both sides agree
on `name` and `kind`, so types match by construction.

For M1 the catalog is hardcoded in `src/fallback_catalog.json`; M2 will
generate WidgetSpec lists from each model's OpenAPI 3.0 schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class WidgetSpec:
    name: str
    kind: str  # "STRING" | "INT" | "FLOAT" | "BOOLEAN" | "COMBO" | "IMAGE_INPUT" | "IMAGE_ARRAY" | "JSON"
    default: Any = None
    options: list[Any] = field(default_factory=list)  # for COMBO; min/max in `meta` for INT/FLOAT
    required: bool = False
    multiline: bool = False  # STRING
    meta: dict[str, Any] = field(default_factory=dict)  # min, max, step, max_items, etc.
    payload_key: str | None = None  # name in the fal payload (defaults to `name`)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WidgetSpec":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @property
    def fal_key(self) -> str:
        return self.payload_key or self.name


@dataclass
class ModelEntry:
    id: str  # fal endpoint, e.g. "fal-ai/bytedance/seedance/v1/lite/image-to-video"
    display_name: str
    category: str  # "text-to-video" | "image-to-video" | ...
    shape: str  # "text_only" | "single_image" | "flf" | "multi_ref"
    description: str = ""
    widgets: list[WidgetSpec] = field(default_factory=list)
    # Pricing from fal's /v1/models/pricing API. None when unavailable.
    unit_price: float | None = None
    unit: str | None = None  # "image", "second", "megapixel", "1M_tokens", etc.
    currency: str | None = None  # "USD" today; stored for future-proofing

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "category": self.category,
            "shape": self.shape,
            "description": self.description,
            "widgets": [w.to_dict() for w in self.widgets],
            "unit_price": self.unit_price,
            "unit": self.unit,
            "currency": self.currency,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelEntry":
        widgets = [WidgetSpec.from_dict(w) for w in data.get("widgets", [])]
        return cls(
            id=data["id"],
            display_name=data["display_name"],
            category=data["category"],
            shape=data["shape"],
            description=data.get("description", ""),
            widgets=widgets,
            unit_price=data.get("unit_price"),
            unit=data.get("unit"),
            currency=data.get("currency"),
        )
