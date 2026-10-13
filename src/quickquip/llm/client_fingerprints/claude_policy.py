"""File-defined Claude Messages identity, caching and conditional beta projection."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import re
from typing import Any

from quickquip.llm.config_errors import ConfigError


@dataclass(frozen=True, slots=True)
class ClaudeBodyPolicy:
    identity_text: str
    field_order: tuple[str, ...]
    metadata_user_id: bool
    context_management_json: str
    cache_system: bool
    cache_tools: bool
    cache_message_tail: bool


@dataclass(frozen=True, slots=True)
class BetaRule:
    name: str
    when: str
    threshold: int = 0


def _invalid(location: str) -> None:
    raise ConfigError("invalid_profile", "Invalid Claude Messages policy", location)


def parse_claude_policy(raw: Any, location: str) -> ClaudeBodyPolicy:
    fields = {"strategy", "identity_text", "field_order", "metadata_user_id",
              "context_management", "cache_system", "cache_tools", "cache_message_tail"}
    if not isinstance(raw, dict) or set(raw) != fields:
        _invalid(location)
    if raw["strategy"] != "claude-code-messages":
        _invalid(location)
    text, order = raw["identity_text"], raw["field_order"]
    if (not isinstance(text, str) or not text.strip() or not isinstance(order, list)
            or any(not isinstance(k, str) or not k for k in order)
            or len(set(order)) != len(order) or not {"model", "messages", "system"} <= set(order)):
        _invalid(location)
    for key in ("metadata_user_id", "cache_system", "cache_tools", "cache_message_tail"):
        if type(raw[key]) is not bool:
            _invalid(location)
    if not isinstance(raw["context_management"], dict):
        _invalid(location)
    try:
        context_json = json.dumps(raw["context_management"], ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError):
        _invalid(location)
    return ClaudeBodyPolicy(
        text, tuple(order), raw["metadata_user_id"], context_json,
        raw["cache_system"], raw["cache_tools"], raw["cache_message_tail"],
    )


def parse_beta_rules(raw: Any, protocol: str, location: str) -> tuple[BetaRule, ...]:
    conditions = {"always", "context_window_above", "tools_thinking_or_effort",
                  "effort", "json_schema"}
    if protocol != "claude" or not isinstance(raw, list):
        _invalid(location)
    rules = []
    seen = set()
    for entry in raw:
        if (not isinstance(entry, dict) or set(entry) - {"name", "when", "threshold"}
                or not {"name", "when"} <= set(entry)):
            _invalid(location)
        name, condition = entry["name"], entry["when"]
        if (not isinstance(name, str) or not re.fullmatch(r"[a-z0-9-]+", name)
                or name in seen or not isinstance(condition, str) or condition not in conditions):
            _invalid(location)
        threshold = entry.get("threshold", 0)
        if (type(threshold) is not int or threshold < 0
                or (condition == "context_window_above" and threshold == 0)
                or (condition != "context_window_above" and "threshold" in entry)):
            _invalid(location)
        seen.add(name)
        rules.append(BetaRule(name, condition, threshold))
    return tuple(rules)


def thinking_enabled(payload: dict) -> bool:
    value = payload.get("thinking")
    return isinstance(value, dict) and value.get("type") in ("adaptive", "enabled")


def derive_beta(rules: tuple[BetaRule, ...], payload: dict, window: int | None) -> str:
    output = payload.get("output_config")
    output = output if isinstance(output, dict) else {}
    output_format = output.get("format")
    matches = {
        "always": True,
        "tools_thinking_or_effort": bool(payload.get("tools")) or thinking_enabled(payload)
        or bool(output.get("effort")),
        "effort": bool(output.get("effort")),
        "json_schema": isinstance(output_format, dict)
        and output_format.get("type") == "json_schema",
    }
    return ",".join(rule.name for rule in rules if (
        window is not None and window > rule.threshold
        if rule.when == "context_window_above" else matches[rule.when]
    ))


def validate_claude_overrides(policy: ClaudeBodyPolicy, overrides: dict,
                              location: str = "extra_body") -> None:
    for field in ("system", "messages", "tools"):
        if field in overrides:
            raise ConfigError("profile_owned_body", "CC Body structure is Profile-owned",
                              f"{location}.{field}")
    if "metadata" in overrides:
        metadata = overrides["metadata"]
        if not isinstance(metadata, dict):
            raise ConfigError("invalid_field", "metadata must be an object", f"{location}.metadata")
        if policy.metadata_user_id and "user_id" in metadata:
            raise ConfigError("profile_owned_body", "CC user_id is Profile-owned",
                              f"{location}.metadata.user_id")


def _cache_blocks(payload: dict):
    """Yield only API cache positions; tool inputs and result text remain opaque."""
    yield from payload.get("system", [])
    yield from payload.get("tools", [])
    for message in payload.get("messages", []):
        content = message.get("content")
        if isinstance(content, list):
            yield from _content_blocks(content)


def _content_blocks(content: list):
    for block in content:
        yield block
        if (isinstance(block, dict) and block.get("type") == "tool_result"
                and isinstance(block.get("content"), list)):
            yield from _content_blocks(block["content"])


def project_claude_body(
    policy: ClaudeBodyPolicy, payload: dict, *, user_id: str | None,
    use_cache: bool, cache_ttl: str, stream: bool,
) -> dict:
    result = deepcopy(payload)
    result["system"] = [{"type": "text", "text": policy.identity_text}, *result["system"]]
    if policy.metadata_user_id:
        result["metadata"] = {**result.get("metadata", {}), "user_id": user_id}
    if thinking_enabled(result) and policy.context_management_json != "{}":
        result.setdefault("context_management", json.loads(policy.context_management_json))
    for block in _cache_blocks(result):
        if isinstance(block, dict):
            block.pop("cache_control", None)
    cache = {"type": "ephemeral"}
    if cache_ttl:
        cache["ttl"] = cache_ttl
    if use_cache:
        if policy.cache_system:
            for block in result["system"]:
                block["cache_control"] = dict(cache)
        if policy.cache_tools and result.get("tools"):
            result["tools"][-1]["cache_control"] = dict(cache)
        if policy.cache_message_tail and result.get("messages"):
            tail = result["messages"][-1]
            if isinstance(tail.get("content"), str) and tail["content"]:
                tail["content"] = [{"type": "text", "text": tail["content"]}]
            blocks = tail.get("content")
            if isinstance(blocks, list):
                for block in reversed(blocks):
                    if isinstance(block, dict) and block.get("type") not in (
                        "thinking", "redacted_thinking",
                    ):
                        block["cache_control"] = dict(cache)
                        break
    if sum("cache_control" in block for block in _cache_blocks(result)
           if isinstance(block, dict)) > 4:
        raise ConfigError("invalid_profile", "Claude supports at most four cache breakpoints")
    result["stream"] = stream
    return {**{k: result[k] for k in policy.field_order if k in result},
            **{k: v for k, v in result.items() if k not in policy.field_order}}
