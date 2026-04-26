"""OpenAPI 3.0 → WidgetSpec list + shape detection for fal.ai models.

Walks the input schema referenced from the model's POST endpoint, dereferences
`$ref` against `components.schemas`, and emits one WidgetSpec per property
plus a shape classification (`text_only`, `single_image`, `flf`, `multi_ref`).

Image fields are detected by (in order):
  1. fal-specific UI hints: `_fal_ui_field == "image"` / `ui.field == "image"`
     either at the top level of the property or inside one of its `anyOf`
     variants.
  2. Name heuristic: the property name contains `image` AND ends in `_url`,
     OR matches one of the well-known shapes (`subject_reference_image_url`,
     `start_image_url`, `end_image_url`, `tail_image_url`, `image_url`).

`anyOf` shapes that are `[<some-type>, "null"]` are normalised to the
non-null variant and the property is marked optional (regardless of whether
it appears in `required`).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from .widget_spec import WidgetSpec


_log = logging.getLogger("fal_gateway.schema")


class SchemaError(Exception):
    """Raised when an OpenAPI doc cannot be parsed into a WidgetSpec list."""


@dataclass
class ParsedSchema:
    widgets: list[WidgetSpec]
    shape: str  # "text_only" | "single_image" | "flf" | "multi_ref"


_MULTILINE_NAMES = {"prompt", "negative_prompt", "description"}
_IMAGE_NAME_RE = re.compile(r"(^|_)image(_url|s|_urls)?$|image_url$|reference_image", re.IGNORECASE)

# Upscale model heuristics. Run only when category == "image-to-image".
_UPSCALE_TAGS = frozenset({"upscaling", "upscaler", "upscale", "super-resolution", "esrgan", "sr"})
_UPSCALE_NAME_RE = re.compile(r"upscal|esrgan|/sr-|-sr$|/sr$|super[-_]res", re.IGNORECASE)
_UPSCALE_KEYWORDS = ("upscale", "upscaling", "super-resolution", "super resolution")


def parse_openapi(
    openapi: dict[str, Any],
    category: str,
    metadata: dict[str, Any] | None = None,
    endpoint_id: str | None = None,
) -> ParsedSchema:
    """Parse a fal model's OpenAPI doc into a WidgetSpec list + shape.

    `metadata` is the model's `metadata` block from the catalog response (tags,
    description, display_name, etc.). Used for upscale shape detection — for
    `image-to-image` models we additionally inspect tags / endpoint name /
    description to flag super-resolution endpoints as `shape="upscale"`.

    `endpoint_id` likewise feeds upscale detection (regex over the path).

    Both are optional for backwards compatibility; without them upscale
    detection is conservative (no tag/name signals → may classify upscalers
    as `single_image` instead).
    """
    schema = _resolve_input_schema(openapi)
    properties = schema.get("properties") or {}
    required_set = set(schema.get("required") or [])

    widgets: list[WidgetSpec] = []
    for name, raw in properties.items():
        widget = _property_to_widget(name, raw, name in required_set)
        if widget is not None:
            widgets.append(widget)

    shape = _detect_shape(widgets, category, metadata=metadata, endpoint_id=endpoint_id)
    return ParsedSchema(widgets=widgets, shape=shape)


def _resolve_input_schema(openapi: dict[str, Any]) -> dict[str, Any]:
    paths = openapi.get("paths") or {}
    for _path, methods in paths.items():
        post = (methods or {}).get("post")
        if not post:
            continue
        rb = (
            (post.get("requestBody") or {})
            .get("content", {})
            .get("application/json", {})
            .get("schema")
        )
        if rb is None:
            continue
        return _resolve_ref(rb, openapi)
    raise SchemaError("no POST request body schema found in openapi.paths")


def _resolve_ref(node: Any, openapi: dict[str, Any]) -> Any:
    """Follow $ref pointers (#/components/schemas/...) until we hit a concrete dict."""
    seen: set[str] = set()
    while isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"]
        if ref in seen:
            raise SchemaError(f"circular $ref detected at {ref}")
        seen.add(ref)
        if not ref.startswith("#/"):
            raise SchemaError(f"unsupported $ref form: {ref}")
        parts = ref.lstrip("#/").split("/")
        target: Any = openapi
        for p in parts:
            target = (target or {}).get(p) if isinstance(target, dict) else None
        if target is None:
            raise SchemaError(f"$ref target not found: {ref}")
        node = target
    return node


def _flatten_anyof(raw: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """If the property uses anyOf with [type, null], return (non-null variant, nullable=True)."""
    any_of = raw.get("anyOf")
    if not any_of:
        return raw, False
    non_null = [v for v in any_of if (v or {}).get("type") != "null"]
    has_null = any((v or {}).get("type") == "null" for v in any_of)
    if not non_null:
        return raw, has_null
    chosen = non_null[0]
    merged = dict(chosen)
    for k in ("default", "description", "title", "examples", "minimum", "maximum",
              "_fal_ui_field", "ui"):
        if k not in merged and k in raw:
            merged[k] = raw[k]
    return merged, has_null


def _is_image_field(name: str, raw: dict[str, Any]) -> bool:
    if (raw.get("ui") or {}).get("field") == "image":
        return True
    if raw.get("_fal_ui_field") == "image":
        return True
    for variant in raw.get("anyOf") or []:
        if isinstance(variant, dict):
            if (variant.get("ui") or {}).get("field") == "image":
                return True
            if variant.get("_fal_ui_field") == "image":
                return True
    if _IMAGE_NAME_RE.search(name):
        return True
    return False


def _is_image_array(name: str, raw: dict[str, Any]) -> bool:
    if (raw.get("type") or "") != "array":
        return False
    nl = name.lower()
    if "image" in nl and ("url" in nl or nl.endswith("_urls")):
        return True
    items = raw.get("items") or {}
    if isinstance(items, dict):
        if items.get("type") == "string" and "image" in nl:
            return True
        props = (items.get("properties") or {})
        if any(_is_image_field(k, v) for k, v in props.items()):
            return True
    return False


def _property_to_widget(name: str, raw: dict[str, Any], required: bool) -> WidgetSpec | None:
    if not isinstance(raw, dict):
        return None

    if _is_image_array(name, raw):
        return WidgetSpec(
            name=name,
            kind="IMAGE_ARRAY",
            required=required,
            payload_key=name,
            meta={"max_items": 4},
        )

    flat, nullable = _flatten_anyof(raw)
    effective_required = required and not nullable

    if _is_image_field(name, raw):
        return WidgetSpec(
            name=name,
            kind="IMAGE_INPUT",
            required=effective_required,
            payload_key=name,
        )

    t = flat.get("type")
    enum = flat.get("enum")
    default = flat.get("default")

    if t == "string":
        if enum:
            return WidgetSpec(
                name=name,
                kind="COMBO",
                default=default if default is not None else (enum[0] if enum else None),
                options=list(enum),
                required=effective_required,
                payload_key=name,
            )
        return WidgetSpec(
            name=name,
            kind="STRING",
            default=default if default is not None else "",
            required=effective_required,
            multiline=name in _MULTILINE_NAMES,
            payload_key=name,
        )

    if t == "integer":
        meta: dict[str, Any] = {}
        if "minimum" in flat:
            meta["min"] = flat["minimum"]
        if "maximum" in flat:
            meta["max"] = flat["maximum"]
        return WidgetSpec(
            name=name,
            kind="INT",
            default=default if default is not None else 0,
            required=effective_required,
            meta=meta,
            payload_key=name,
        )

    if t == "number":
        meta = {}
        if "minimum" in flat:
            meta["min"] = flat["minimum"]
        if "maximum" in flat:
            meta["max"] = flat["maximum"]
        if "multipleOf" in flat:
            meta["step"] = flat["multipleOf"]
        return WidgetSpec(
            name=name,
            kind="FLOAT",
            default=default if default is not None else 0.0,
            required=effective_required,
            meta=meta,
            payload_key=name,
        )

    if t == "boolean":
        return WidgetSpec(
            name=name,
            kind="BOOLEAN",
            default=bool(default) if default is not None else False,
            required=effective_required,
            payload_key=name,
        )

    if t == "array":
        return WidgetSpec(
            name=name,
            kind="STRING",
            default="",
            required=effective_required,
            multiline=True,
            payload_key=name,
            meta={"is_array": True},
        )

    if t == "object":
        return WidgetSpec(
            name=name,
            kind="JSON",
            default="",
            required=effective_required,
            multiline=True,
            payload_key=name,
        )

    _log.debug("schema_resolver: skipping unknown type for %s: %s", name, t)
    return None


def _detect_shape(
    widgets: list[WidgetSpec],
    category: str,
    metadata: dict[str, Any] | None = None,
    endpoint_id: str | None = None,
) -> str:
    if category in ("text-to-video", "text-to-image"):
        return "text_only"

    if category == "image-to-image" and _looks_like_upscale(metadata, endpoint_id):
        return "upscale"

    image_inputs = [w for w in widgets if w.kind == "IMAGE_INPUT"]
    image_arrays = [w for w in widgets if w.kind == "IMAGE_ARRAY"]

    if image_arrays:
        return "multi_ref"
    if len(image_inputs) >= 2:
        return "flf"
    if len(image_inputs) == 1:
        return "single_image"
    return "text_only"


def _looks_like_upscale(
    metadata: dict[str, Any] | None,
    endpoint_id: str | None,
) -> bool:
    """Heuristic: does this image-to-image model look like an upscaler?

    Three signals (any one suffices):
      1. metadata.tags intersects {upscaling, upscaler, upscale, super-resolution, esrgan, sr}
      2. endpoint_id matches the upscale name pattern (esrgan, /sr-..., upscal..., super-res)
      3. metadata.description contains a known upscale keyword

    Conservative: returns False if all signals absent, even if the model is
    technically an upscaler. False positives are resolvable by a user override
    in fallback_catalog.json; false negatives just mean the model shows in I2I
    instead of Upscale.
    """
    meta = metadata or {}

    tags = meta.get("tags") or []
    if isinstance(tags, list):
        normalized = {str(t).lower() for t in tags if isinstance(t, str)}
        if normalized & _UPSCALE_TAGS:
            return True

    if endpoint_id and _UPSCALE_NAME_RE.search(endpoint_id):
        return True

    desc = (meta.get("description") or "")
    if isinstance(desc, str):
        desc_l = desc.lower()
        if any(k in desc_l for k in _UPSCALE_KEYWORDS):
            return True

    return False
