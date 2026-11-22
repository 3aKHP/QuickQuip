from __future__ import annotations

import json

import httpx

from quickquip.llm.provider.base import LLMProviderError
from quickquip.llm.provider.gemini_compat import (
    SKIP_THOUGHT_SIGNATURE,
    downgrade_thought_signatures,
    is_empty_text_part,
    is_thought_signature_rejection,
    sanitize_model_parts,
)


def _http_400(body: dict | str, *, status_code: int = 400) -> LLMProviderError:
    raw = body if isinstance(body, str) else json.dumps(body)
    request = httpx.Request("POST", "https://example.test/v1beta/models/m:generateContent")
    response = httpx.Response(status_code, text=raw, request=request)
    cause = httpx.HTTPStatusError(f"HTTP {status_code}", request=request, response=response)
    err = LLMProviderError(
        f"HTTP {status_code} {raw[:240]}",
        status_code=status_code,
        http_reject=True,
    )
    err.__cause__ = cause
    return err


def test_is_empty_text_part_matrix():
    assert is_empty_text_part({"text": ""}) is True
    assert is_empty_text_part({"text": "", "thought": True}) is True
    assert is_empty_text_part({"thought": True}) is True
    assert is_empty_text_part({}) is True

    assert is_empty_text_part({"text": " "}) is False
    assert is_empty_text_part({"text": "hello"}) is False
    assert is_empty_text_part({"text": "", "thoughtSignature": "sig-1"}) is False
    assert is_empty_text_part({"thoughtSignature": "sig-1"}) is False
    assert is_empty_text_part({"functionCall": {"name": "foo", "args": {}}}) is False
    assert is_empty_text_part({"inlineData": {"mimeType": "image/png", "data": "AA=="}}) is False
    assert is_empty_text_part("not-a-dict") is False


def test_sanitize_model_parts_filters_empty_and_fills_missing_call_signatures():
    raw_parts = [
        {"text": "", "thought": True},
        {"functionCall": {"id": "c1", "name": "tool_a", "args": {}}},
        {
            "functionCall": {"id": "c2", "name": "tool_b", "args": {}},
            "thoughtSignature": "real-sig",
        },
        {"text": ""},
        {"text": "", "thoughtSignature": "carrier-sig"},
        {"text": "answer"},
    ]
    sanitized = sanitize_model_parts(raw_parts)
    assert sanitized == [
        {
            "functionCall": {"id": "c1", "name": "tool_a", "args": {}},
            "thoughtSignature": SKIP_THOUGHT_SIGNATURE,
        },
        {
            "functionCall": {"id": "c2", "name": "tool_b", "args": {}},
            "thoughtSignature": "real-sig",
        },
        {"text": "", "thoughtSignature": "carrier-sig"},
        {"text": "answer"},
    ]
    # Original input must not be mutated.
    assert "thoughtSignature" not in raw_parts[1]


def test_is_thought_signature_rejection_recognizes_google_and_relay_formats():
    google_native = _http_400({
        "error": {
            "code": 400,
            "message": "Invalid thought signature.",
            "status": "INVALID_ARGUMENT",
        }
    })
    relay_missing = _http_400({
        "error": {
            "message": "Function call is missing a thought_signature in functionCall parts.",
            "type": "upstream_error",
            "param": "",
            "code": "upstream_error",
        }
    })
    plain_error = LLMProviderError(
        'HTTP 400 {"error":{"message":"Thought signature is not valid"}}',
        status_code=400,
        http_reject=True,
    )
    unrelated_400 = _http_400({
        "error": {
            "code": 400,
            "message": "GenerateContentRequest.contents[5].parts[1].data: required oneof field",
            "status": "INVALID_ARGUMENT",
        }
    })
    server_500 = _http_400(
        {"error": {"message": "Invalid thought signature."}},
        status_code=500,
    )
    non_http_reject = LLMProviderError(
        "Invalid thought signature.",
        status_code=400,
        http_reject=False,
    )

    assert is_thought_signature_rejection(google_native) is True
    assert is_thought_signature_rejection(relay_missing) is True
    assert is_thought_signature_rejection(plain_error) is True
    assert is_thought_signature_rejection(unrelated_400) is False
    assert is_thought_signature_rejection(server_500) is False
    assert is_thought_signature_rejection(non_http_reject) is False


def test_downgrade_thought_signatures_preserves_calls_and_drops_empty_carriers():
    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": "hi"}]},
            {
                "role": "model",
                "parts": [
                    {"text": "thinking...", "thought": True, "thoughtSignature": "sig-thought"},
                    {"text": "", "thoughtSignature": "sig-empty-carrier"},
                    {
                        "functionCall": {"id": "c1", "name": "search", "args": {"q": "a"}},
                        "thoughtSignature": "sig-call",
                    },
                ],
            },
            {
                "role": "user",
                "parts": [
                    {
                        "functionResponse": {
                            "id": "c1",
                            "name": "search",
                            "response": {"content": "ok"},
                        }
                    }
                ],
            },
            {
                "role": "model",
                "parts": [
                    {"text": "", "thoughtSignature": "sig-only-turn"},
                ],
            },
            {
                "role": "model",
                "parts": [
                    {"text": "final reply", "thoughtSignature": "sig-text"},
                ],
            },
        ]
    }
    downgraded, changed = downgrade_thought_signatures(payload)
    assert changed == 5
    assert downgraded["contents"] == [
        {"role": "user", "parts": [{"text": "hi"}]},
        {
            "role": "model",
            "parts": [
                {"text": "thinking...", "thought": True},
                {
                    "functionCall": {"id": "c1", "name": "search", "args": {"q": "a"}},
                    "thoughtSignature": SKIP_THOUGHT_SIGNATURE,
                },
            ],
        },
        {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "id": "c1",
                        "name": "search",
                        "response": {"content": "ok"},
                    }
                }
            ],
        },
        {
            "role": "model",
            "parts": [{"text": "final reply"}],
        },
    ]
    # Second pass is a no-op so retry loops cannot spin.
    second, second_changed = downgrade_thought_signatures(downgraded)
    assert second_changed == 0
    assert second is downgraded
