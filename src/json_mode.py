"""Schema-as-toggle JSON output mode for T2T / I2T.

A non-empty `schema` widget on `FalGatewayT2T` / `FalGatewayI2T` switches
the LLM call from free-form text into structured JSON output via
OpenRouter's `response_format: {"type": "json_schema", ...}` parameter.
Empty schema preserves the existing text-output behavior.

This module owns the schema → `response_format` conversion. The orchestrator
`apply_schema_to_payload` runs in `_FalGatewayNodeBase.execute()` between
the catalog `extra_payload` merge and the endpoint-specific transformer,
so the existing transformer code stays unchanged (the new key just passes
through).

Schema format for v1: comma-separated field names. Each field becomes a
`string` property in the generated JSON Schema. Future extensibility (full
JSON Schema input) is intentionally deferred — see the design doc.
"""

from __future__ import annotations

from typing import Any


# Endpoints known to honor OpenRouter's `response_format` parameter. fal-direct
# vision/LLM endpoints (Florence-2, Moondream, Bytedance Seed, Nemotron, etc.)
# don't pass this through, so the schema kwarg is dropped silently for them.
_RESPONSE_FORMAT_ENDPOINTS: frozenset[str] = frozenset(
    {
        "openrouter/router/openai/v1/chat/completions",
        "openrouter/router/vision",
    }
)


def parse_schema_fields(schema_str: str) -> list[str]:
    """Split a comma-separated field list, strip whitespace, drop empties."""
    if not schema_str:
        return []
    return [f.strip() for f in schema_str.split(",") if f.strip()]


def build_response_format(fields: list[str]) -> dict[str, Any] | None:
    """Wrap field names into OpenRouter's strict json_schema envelope.

    Returns None when the field list is empty so callers can early-out.
    """
    if not fields:
        return None
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "user_schema",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {f: {"type": "string"} for f in fields},
                "required": list(fields),
                "additionalProperties": False,
            },
        },
    }


def augment_system_prompt(existing: str, fields: list[str]) -> str:
    """Append a "Output STRICT JSON with these fields: …" instruction.

    Belt-and-suspenders alongside `response_format`: even if the upstream
    model has flaky strict-mode adherence, the system message nudges it
    toward the right shape. For models without strict-mode support, this
    is the only signal.
    """
    if not fields:
        return existing
    instruction = (
        f"Output STRICT JSON with exactly these fields: {', '.join(fields)}. "
        "Each value must be a string. Do not include any text outside the JSON object."
    )
    if existing.strip():
        return f"{existing.rstrip()}\n\n{instruction}"
    return instruction


def apply_schema_to_payload(payload: dict[str, Any], endpoint_id: str) -> dict[str, Any]:
    """Convert a `schema` kwarg in the payload into `response_format` + a
    system-prompt augmentation, in place on a shallow copy.

    Steps:
    1. Pop `schema` from payload — it's never sent to fal as a raw field.
    2. If empty / whitespace-only → return without further changes.
    3. For endpoints that honor `response_format`, inject the json_schema envelope.
    4. Always augment `system_prompt` (best-effort fallback for non-strict models
       and a hint for endpoints that don't accept response_format but do have
       a system prompt field).
    """
    out = dict(payload)
    schema_str = out.pop("schema", None)
    if not isinstance(schema_str, str):
        return out
    fields = parse_schema_fields(schema_str)
    if not fields:
        return out

    if endpoint_id in _RESPONSE_FORMAT_ENDPOINTS:
        rf = build_response_format(fields)
        if rf is not None:
            out["response_format"] = rf

    # Augment system_prompt only when the endpoint accepts that field — i.e.
    # whitelisted OpenRouter routers, OR an upstream layer already populated
    # one. Fabricating system_prompt for fal-direct endpoints (Florence-2,
    # Moondream, Bytedance Seed) risks request-validation failures since
    # their OpenAPI schemas don't declare it.
    existing_system_prompt = out.get("system_prompt")
    if endpoint_id in _RESPONSE_FORMAT_ENDPOINTS or existing_system_prompt:
        out["system_prompt"] = augment_system_prompt(existing_system_prompt or "", fields)
    return out
