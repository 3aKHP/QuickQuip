"""File-defined OpenAI Chat layout, endpoint compatibility and pure lowering."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlsplit

from quickquip.llm.config_errors import ConfigError

_BOOL_FIELDS = (
    "supports_store", "supports_strict_mode", "supports_usage_in_streaming", "tool_stream",
)
_COMPAT_FIELDS = ("max_tokens_field", *_BOOL_FIELDS)


@dataclass(frozen=True, slots=True)
class EndpointRule:
    hosts: tuple[str, ...]
    providers: tuple[str, ...]
    exclude_models: tuple[str, ...]
    changes: tuple[tuple[str, str | bool], ...]


@dataclass(frozen=True, slots=True)
class ChatBodyPolicy:
    field_order: tuple[str, ...]
    tool_message_fields: tuple[str, ...]
    omit_auto_tool_choice: bool
    assistant_tool_empty_null: bool
    max_tokens_field: str
    supports_store: bool
    supports_strict_mode: bool
    supports_usage_in_streaming: bool
    tool_stream: bool
    endpoint_rules: tuple[EndpointRule, ...] = ()
    assistant_field_order: tuple[str, ...] = ()


def _invalid(location: str) -> None:
    raise ConfigError("invalid_profile", "Invalid Chat Body policy", location)


def _strings(value, location: str, *, empty=False) -> tuple[str, ...]:
    if (not isinstance(value, list) or (not value and not empty)
            or any(not isinstance(v, str) or not v.strip() for v in value)
            or len(set(value)) != len(value)):
        _invalid(location)
    return tuple(value)


def _compat(raw: dict, location: str) -> dict:
    if "max_tokens_field" in raw and raw["max_tokens_field"] not in (
        "max_tokens", "max_completion_tokens",
    ):
        _invalid(location)
    if any(type(raw[k]) is not bool for k in _BOOL_FIELDS if k in raw):
        _invalid(location)
    return {k: raw[k] for k in _COMPAT_FIELDS if k in raw}


def parse_body_policy(raw, protocol: str, location: str) -> ChatBodyPolicy:
    fields = {"strategy", "field_order", "tool_message_fields", "omit_auto_tool_choice",
              "assistant_tool_empty_null", "endpoint_rules", "assistant_field_order",
              *_COMPAT_FIELDS}
    if (protocol != "openai" or not isinstance(raw, dict) or set(raw) - fields
            or raw.get("strategy") != "openai-chat-native"
            or not (fields - {"endpoint_rules", "assistant_field_order"}).issubset(raw)):
        _invalid(location)
    for key in ("omit_auto_tool_choice", "assistant_tool_empty_null"):
        if type(raw[key]) is not bool:
            _invalid(location)
    order = _strings(raw["field_order"], location)
    if not {"model", "messages"}.issubset(order):
        _invalid(location)
    tool_fields = _strings(raw["tool_message_fields"], location)
    if (not {"role", "tool_call_id", "content"}.issubset(tool_fields)
            or set(tool_fields) - {"role", "tool_call_id", "content", "name"}):
        _invalid(location)
    raw_rules = raw.get("endpoint_rules", [])
    if not isinstance(raw_rules, list):
        _invalid(location)
    rules = []
    for rule in raw_rules:
        if (not isinstance(rule, dict)
                or set(rule) - {"hosts", "providers", "exclude_models", *_COMPAT_FIELDS}):
            _invalid(location)
        hosts = _strings(rule.get("hosts", []), location, empty=True)
        providers = _strings(rule.get("providers", []), location, empty=True)
        excluded = _strings(rule.get("exclude_models", []), location, empty=True)
        if not hosts and not providers:
            _invalid(location)
        if any(h != h.lower() or not h or any(c not in
               "abcdefghijklmnopqrstuvwxyz0123456789.-" for c in h) for h in hosts):
            _invalid(location)
        rules.append(EndpointRule(hosts=hosts, providers=tuple(v.lower() for v in providers),
                                  exclude_models=tuple(v.lower() for v in excluded),
                                  changes=tuple(_compat(rule, location).items())))
    compat = _compat(raw, location)
    assistant_order = _strings(raw.get("assistant_field_order", []), location, empty=True)
    return ChatBodyPolicy(field_order=order, tool_message_fields=tool_fields,
                          omit_auto_tool_choice=raw["omit_auto_tool_choice"],
                          assistant_tool_empty_null=raw["assistant_tool_empty_null"],
                          **compat, endpoint_rules=tuple(rules),
                          assistant_field_order=assistant_order)


def resolve_body_policy(policy: ChatBodyPolicy, url: str, provider: str, model: str):
    host = (urlsplit(url).hostname or "").lower()
    result = policy
    for rule in policy.endpoint_rules:
        if model.lower() in rule.exclude_models:
            continue
        if (provider.lower() in rule.providers
                or any(host == h or host.endswith("." + h) for h in rule.hosts)):
            result = replace(result, **dict(rule.changes))
    return result


def validate_body_overrides(overrides: dict, location="extra_body") -> None:
    if "max_tokens" in overrides and "max_completion_tokens" in overrides:
        raise ConfigError("invalid_field", "Configure only one max token field", location)


def project_chat_body(
    policy: ChatBodyPolicy, payload: dict[str, Any], *, url: str, provider: str,
    stream: bool, overrides: dict[str, Any],
) -> dict[str, Any]:
    validate_body_overrides(overrides)
    result = deepcopy(payload)
    policy = resolve_body_policy(policy, url, provider, str(result.get("model", "")))
    limit = result.pop("max_tokens", result.pop("max_completion_tokens", None))
    # The raw adapter payload owns the business budget; compatibility chooses its wire key.
    if limit is not None:
        result[policy.max_tokens_field] = limit
    result["stream"] = stream
    if stream and policy.supports_usage_in_streaming:
        result["stream_options"] = {"include_usage": True}
    else:
        result.pop("stream_options", None)
    if policy.supports_store:
        result.setdefault("store", False)
    else:
        result.pop("store", None)
    for index, message in enumerate(result.get("messages", [])):
        if message.get("role") == "tool":
            for name in tuple(message):
                if name not in policy.tool_message_fields:
                    del message[name]
            result["messages"][index] = {k: message[k] for k in policy.tool_message_fields
                                         if k in message}
        elif (message.get("role") == "assistant" and message.get("tool_calls")
              and not message.get("content") and policy.assistant_tool_empty_null):
            message["content"] = None
        if message.get("role") == "assistant":
            order = policy.assistant_field_order
            result["messages"][index] = {
                **{k: message[k] for k in order if k in message},
                **{k: v for k, v in message.items() if k not in order},
            }
    tools = result.get("tools", [])
    if tools:
        for tool in tools:
            if tool.get("type") == "function":
                if policy.supports_strict_mode:
                    tool["function"]["strict"] = False
                else:
                    tool["function"].pop("strict", None)
        if policy.tool_stream:
            result["tool_stream"] = True
    else:
        result.pop("tool_choice", None)
        if any(m.get("role") == "tool" or m.get("tool_calls")
               for m in result.get("messages", [])):
            result["tools"] = []
    if policy.omit_auto_tool_choice and result.get("tool_choice") == "auto":
        result.pop("tool_choice")
    # Explicit administrator choices win over profile defaults, including non-standard fields.
    if "max_tokens" in overrides or "max_completion_tokens" in overrides:
        result.pop("max_tokens", None)
        result.pop("max_completion_tokens", None)
    result.update(deepcopy(overrides))
    return {**{k: result[k] for k in policy.field_order if k in result},
            **{k: v for k, v in result.items() if k not in policy.field_order}}
