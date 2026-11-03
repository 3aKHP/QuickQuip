"""Bounded GenerateContent continuation for MAX_TOKENS responses without output."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from quickquip.llm.config import ProviderConfig
from quickquip.llm.provider.base import LLMResponse


def empty_response_recovery_payload(
    config: ProviderConfig,
    payload: dict[str, Any],
    body: dict[str, Any],
    response: LLMResponse,
) -> dict[str, Any] | None:
    """Retain the original prompt and opaque token; raise only the output limit."""
    if (
        not config.gemini_empty_response_recovery
        or response.finish_reason != "MAX_TOKENS"
        or response.text.strip()
        or response.tool_calls
        or response.generated_images
        or "continuationToken" in payload
    ):
        return None
    candidates = body.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        return None
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        return None
    token = candidate.get("continuationToken")
    if not isinstance(token, str) or not token.strip():
        return None
    # Audio and other non-text output also constitute a result, even though
    # LLMResponse currently exposes only text, function calls and images.
    content = candidate.get("content") or {}
    if not isinstance(content, dict) or not isinstance(content.get("parts", []), list):
        return None
    for part in content.get("parts", []):
        if not isinstance(part, dict) or set(part) - {"text", "thought", "thoughtSignature"}:
            return None
    generation = payload.get("generationConfig")
    limit = generation.get("maxOutputTokens") if isinstance(generation, dict) else None
    if type(limit) is not int or limit <= 0:
        return None
    expanded = min(limit * 2, config.gemini_empty_response_recovery_max_output_tokens)
    if expanded <= limit:
        return None
    recovered = deepcopy(payload)
    recovered["continuationToken"] = token
    recovered["generationConfig"]["maxOutputTokens"] = expanded
    return recovered


def sum_recovery_usage(initial: LLMResponse, recovered: LLMResponse) -> None:
    """REST usage is per HTTP request; retain both requests' reported usage."""
    for name in (
        "input_tokens", "output_tokens", "cache_creation_tokens",
        "cache_read_tokens", "thinking_tokens",
    ):
        first, second = getattr(initial, name), getattr(recovered, name)
        setattr(
            recovered, name,
            (first or 0) + (second or 0) if first is not None or second is not None else None,
        )
