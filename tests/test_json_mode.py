"""Tests for src/json_mode.py — the schema → response_format orchestrator.

Schema-as-toggle: an empty schema preserves current text-output behavior; a
non-empty comma-separated field list switches the LLM call into structured
JSON mode via OpenRouter's `response_format` parameter.
"""

from __future__ import annotations

from src.json_mode import (
    apply_schema_to_payload,
    augment_system_prompt,
    build_response_format,
    parse_schema_fields,
)


# ---- parse_schema_fields --------------------------------------------------


def test_parse_schema_fields_empty_returns_empty_list():
    assert parse_schema_fields("") == []
    assert parse_schema_fields("   ") == []


def test_parse_schema_fields_simple_comma_list():
    assert parse_schema_fields("title, tagline, cta") == ["title", "tagline", "cta"]


def test_parse_schema_fields_strips_inner_whitespace():
    assert parse_schema_fields("  title ,  tagline  ,cta") == ["title", "tagline", "cta"]


def test_parse_schema_fields_drops_empty_segments():
    assert parse_schema_fields("title,,tagline,") == ["title", "tagline"]


def test_parse_schema_fields_preserves_underscores_and_hyphens():
    assert parse_schema_fields("flux_ref_prompt, motion-prompt") == [
        "flux_ref_prompt",
        "motion-prompt",
    ]


# ---- build_response_format ------------------------------------------------


def test_build_response_format_shape():
    rf = build_response_format(["title", "tagline"])
    assert rf["type"] == "json_schema"
    js = rf["json_schema"]
    assert js["name"] == "user_schema"
    assert js["strict"] is True
    schema = js["schema"]
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["title", "tagline"]
    assert schema["properties"] == {
        "title": {"type": "string"},
        "tagline": {"type": "string"},
    }


def test_build_response_format_empty_fields_returns_none():
    assert build_response_format([]) is None


# ---- augment_system_prompt ------------------------------------------------


def test_augment_system_prompt_appends_to_existing():
    out = augment_system_prompt("You are helpful.", ["title", "tagline"])
    assert "You are helpful." in out
    assert "title" in out and "tagline" in out
    assert "JSON" in out


def test_augment_system_prompt_works_with_empty_existing():
    out = augment_system_prompt("", ["title"])
    assert out.strip()  # non-empty
    assert "title" in out


def test_augment_system_prompt_no_fields_returns_existing_unchanged():
    assert augment_system_prompt("hello", []) == "hello"
    assert augment_system_prompt("", []) == ""


# ---- apply_schema_to_payload ----------------------------------------------


CHAT_ENDPOINT = "openrouter/router/openai/v1/chat/completions"
VISION_ENDPOINT = "openrouter/router/vision"
FAL_DIRECT_ENDPOINT = "fal-ai/florence-2-large/detailed-caption"


def test_apply_schema_to_payload_no_schema_unchanged():
    payload = {"prompt": "hi", "model": "x"}
    out = apply_schema_to_payload(payload, CHAT_ENDPOINT)
    assert out == payload
    assert "response_format" not in out


def test_apply_schema_to_payload_empty_schema_unchanged():
    payload = {"prompt": "hi", "schema": "   "}
    out = apply_schema_to_payload(payload, CHAT_ENDPOINT)
    assert "schema" not in out, "schema kwarg should always be popped"
    assert "response_format" not in out


def test_apply_schema_to_payload_chat_endpoint_injects_response_format():
    payload = {"prompt": "ad copy", "schema": "title, tagline"}
    out = apply_schema_to_payload(payload, CHAT_ENDPOINT)
    assert "schema" not in out
    assert "response_format" in out
    assert out["response_format"]["json_schema"]["schema"]["required"] == ["title", "tagline"]


def test_apply_schema_to_payload_vision_endpoint_injects_response_format():
    payload = {"prompt": "describe", "schema": "species, mood"}
    out = apply_schema_to_payload(payload, VISION_ENDPOINT)
    assert "response_format" in out
    assert out["response_format"]["json_schema"]["schema"]["required"] == ["species", "mood"]


def test_apply_schema_to_payload_fal_direct_drops_schema_no_response_format():
    """Florence-2 etc. don't support response_format. We pop schema (so it
    doesn't ship to fal as an unknown field) and do NOT synthesize a
    system_prompt either — these endpoints don't accept that field, and
    fabricating it risks request-validation failures."""
    payload = {"prompt": "describe", "schema": "species, mood"}
    out = apply_schema_to_payload(payload, FAL_DIRECT_ENDPOINT)
    assert "schema" not in out
    assert "response_format" not in out
    assert "system_prompt" not in out, (
        "must not fabricate system_prompt for endpoints that don't accept it"
    )


def test_apply_schema_to_payload_fal_direct_with_existing_system_prompt_still_augments():
    """If the user (or upstream code) already supplied a system_prompt for a
    fal-direct endpoint, augmenting is fine — we're not creating an unexpected
    field, just appending to one that's already in flight."""
    payload = {
        "prompt": "describe",
        "system_prompt": "Be terse.",
        "schema": "species, mood",
    }
    out = apply_schema_to_payload(payload, FAL_DIRECT_ENDPOINT)
    assert "system_prompt" in out
    assert "Be terse." in out["system_prompt"]
    assert "species" in out["system_prompt"]


def test_apply_schema_to_payload_augments_system_prompt_on_supported_endpoint():
    payload = {"prompt": "x", "system_prompt": "You are concise.", "schema": "title"}
    out = apply_schema_to_payload(payload, CHAT_ENDPOINT)
    assert "You are concise." in out["system_prompt"]
    assert "title" in out["system_prompt"]


def test_apply_schema_to_payload_creates_system_prompt_if_missing():
    payload = {"prompt": "x", "schema": "title"}
    out = apply_schema_to_payload(payload, CHAT_ENDPOINT)
    assert "system_prompt" in out
    assert "title" in out["system_prompt"]


def test_apply_schema_to_payload_preserves_other_keys():
    payload = {
        "prompt": "x",
        "model": "anthropic/claude-sonnet-4.5",
        "temperature": 0.7,
        "schema": "title",
    }
    out = apply_schema_to_payload(payload, CHAT_ENDPOINT)
    assert out["model"] == "anthropic/claude-sonnet-4.5"
    assert out["temperature"] == 0.7
    assert out["prompt"] == "x"
