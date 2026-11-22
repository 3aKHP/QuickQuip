"""Gemini GenerateContent compatibility helpers for strict upstreams.

Handles three protocol edge cases observed across AI Studio / relay upstreams:
1. Empty text/thought parts (e.g. ``{"text": ""}``) rejected by strict protobuf
   ``oneof data`` validation.
2. Historical ``functionCall`` parts without ``thoughtSignature`` (for example
   after cross-model projection) requiring the official sentinel value.
3. HTTP 400 thought signature rejections when switching between upstreams that
   do not accept each other's opaque signatures, recovered via a bounded
   single-retry downgrade of model-history signatures.
"""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

import httpx

from quickquip.llm.provider.base import LLMProviderError

SKIP_THOUGHT_SIGNATURE = "skip_thought_signature_validator"

_SIGNATURE_REJECTION_PATTERNS = (
    "invalid thought signature",
    "invalid thought_signature",
    "thought signature is not valid",
    "thought_signature is not valid",
    "corrupted thought signature",
    "corrupted thought_signature",
    "missing a thought_signature",
    "missing thought_signature",
    "missing thought signature",
)


def is_empty_text_part(part: Any) -> bool:
    """Return True for parts that carry no initialized payload field.

    Parts carrying ``thoughtSignature``, ``functionCall``, ``inlineData`` or
    other payload fields (including ``{"text": "", "thoughtSignature": "..."}``)
    are preserved.
    """
    return (
        isinstance(part, dict)
        and set(part) <= {"text", "thought"}
        and not part.get("text")
    )


def sanitize_model_parts(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deep-copy model parts, drop empty text parts, and fill missing call signatures."""
    sanitized: list[dict[str, Any]] = []
    for raw_part in parts:
        if not isinstance(raw_part, dict) or is_empty_text_part(raw_part):
            continue
        part = deepcopy(raw_part)
        if isinstance(part.get("functionCall"), dict):
            signature = part.get("thoughtSignature")
            if not isinstance(signature, str) or not signature.strip():
                part["thoughtSignature"] = SKIP_THOUGHT_SIGNATURE
        sanitized.append(part)
    return sanitized


def _extract_error_message(exc: LLMProviderError) -> str:
    raw = ""
    cause = exc.__cause__
    if isinstance(cause, httpx.HTTPStatusError):
        try:
            raw = cause.response.text
        except Exception:
            raw = ""
    if not raw:
        raw = str(exc)
    text = raw.strip()
    if text.startswith("HTTP "):
        parts = text.split(" ", 2)
        if len(parts) == 3:
            text = parts[2].strip()
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return raw.lower()
    if isinstance(obj, dict):
        error = obj.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.lower()
    return raw.lower()


def is_thought_signature_rejection(exc: LLMProviderError) -> bool:
    """Identify HTTP 400 responses explicitly rejecting a thought signature."""
    if exc.status_code != 400 or not exc.http_reject:
        return False
    message = _extract_error_message(exc)
    return any(pattern in message for pattern in _SIGNATURE_REJECTION_PATTERNS)


def downgrade_thought_signatures(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Downgrade model-history thought signatures in a request payload copy.

    - ``functionCall`` parts have any non-sentinel or missing ``thoughtSignature``
      replaced with ``SKIP_THOUGHT_SIGNATURE``.
    - Other model parts have ``thoughtSignature`` stripped; if stripping leaves
      an empty text/thought carrier, that part is dropped.
    - Model turns that become empty after stripping pure signature carriers are
      removed from ``contents``.
    """
    contents = payload.get("contents")
    if not isinstance(contents, list):
        return payload, 0

    downgraded = deepcopy(payload)
    changed = 0
    emptied: set[int] = set()

    for content in downgraded["contents"]:
        if (
            not isinstance(content, dict)
            or content.get("role") != "model"
            or not isinstance(content.get("parts"), list)
        ):
            continue
        original_parts = content["parts"]
        kept_parts: list[Any] = []
        for part in original_parts:
            if not isinstance(part, dict):
                kept_parts.append(part)
                continue
            signature = part.get("thoughtSignature")
            if isinstance(part.get("functionCall"), dict):
                if signature != SKIP_THOUGHT_SIGNATURE:
                    part["thoughtSignature"] = SKIP_THOUGHT_SIGNATURE
                    changed += 1
                kept_parts.append(part)
                continue
            if isinstance(signature, str) and signature and signature != SKIP_THOUGHT_SIGNATURE:
                part.pop("thoughtSignature", None)
                changed += 1
            if is_empty_text_part(part):
                continue
            kept_parts.append(part)
        if original_parts and not kept_parts:
            emptied.add(id(content))
        content["parts"] = kept_parts

    if not changed:
        return payload, 0

    if emptied:
        downgraded["contents"] = [
            content for content in downgraded["contents"] if id(content) not in emptied
        ]
    return downgraded, changed
