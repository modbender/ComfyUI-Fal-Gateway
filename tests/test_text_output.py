"""Tests for output_decoder's "text" kind — used by LLM and VLM nodes.

Text outputs are never downloaded — fal returns the response in the result
dict directly. The text kind has no URL artifact, so:
  - extract_artifact_url(result, "text") returns the response string
  - decode_artifact(url, "text") returns the URL itself unchanged (passthrough)
"""

from __future__ import annotations

import pytest

from src.fal.output_decoder import (
    _text_from_result,
    decode_artifact,
    extract_artifact_url,
)


# ---- _text_from_result ---------------------------------------------------


def test_text_from_result_handles_response_key():
    """Most fal LLMs return the text under `response`."""
    result = {"response": "Hello, world!"}
    assert _text_from_result(result) == "Hello, world!"


def test_text_from_result_handles_output_key():
    """Some endpoints use `output`."""
    result = {"output": "Generated text here."}
    assert _text_from_result(result) == "Generated text here."


def test_text_from_result_handles_text_key():
    """Some endpoints use `text`."""
    result = {"text": "Caption: a snow leopard."}
    assert _text_from_result(result) == "Caption: a snow leopard."


def test_text_from_result_prefers_response_when_multiple_keys_present():
    """Priority order: response > output > text — pick the most-canonical."""
    result = {"response": "from response", "output": "from output", "text": "from text"}
    assert _text_from_result(result) == "from response"


def test_text_from_result_handles_nested_choices_openai_shape():
    """OpenRouter-style: result.choices[0].message.content (mimics OpenAI chat)."""
    result = {"choices": [{"message": {"content": "Chat response."}}]}
    assert _text_from_result(result) == "Chat response."


def test_text_from_result_handles_responses_api_output_text_field():
    """OpenAI Responses API exposes a flat `output_text` convenience string."""
    result = {"output_text": "The capital is Paris."}
    assert _text_from_result(result) == "The capital is Paris."


def test_text_from_result_handles_responses_api_structured_output():
    """OpenAI Responses API: `output` is a list of message-like items, each
    containing `content: [{type: 'output_text', text: '...'}, ...]`."""
    result = {
        "output": [
            {
                "id": "msg_1",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "Structured answer here."}
                ],
            }
        ]
    }
    assert _text_from_result(result) == "Structured answer here."


def test_text_from_result_responses_skips_non_text_content_chunks():
    """Tool-call entries shouldn't be confused with the assistant text."""
    result = {
        "output": [
            {"type": "tool_call", "name": "calc", "arguments": "{}"},
            {
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "After tool: 42"}
                ],
            },
        ]
    }
    assert _text_from_result(result) == "After tool: 42"


def test_text_from_result_raises_on_unknown_shape():
    result = {"foo": "bar", "baz": 42}
    with pytest.raises(RuntimeError) as exc_info:
        _text_from_result(result)
    assert "foo" in str(exc_info.value) or "baz" in str(exc_info.value)


# ---- extract_artifact_url dispatches "text" ------------------------------


def test_extract_artifact_url_dispatches_text():
    result = {"response": "the answer is 42"}
    assert extract_artifact_url(result, "text") == "the answer is 42"


# ---- decode_artifact for "text" kind -------------------------------------


async def test_decode_artifact_text_returns_value_unchanged():
    """Text "decoding" is a no-op — the URL we extracted IS the text."""
    out = await decode_artifact("hello", "text")
    assert out == "hello"
