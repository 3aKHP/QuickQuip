"""File-defined GenerateContent envelope layout; preserve native protocol evidence."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from quickquip.llm.config_errors import ConfigError


@dataclass(frozen=True, slots=True)
class GeminiBodyPolicy:
    field_order: tuple[str, ...]
    content_field_order: tuple[str, ...]
    part_field_order: tuple[str, ...]
    function_call_field_order: tuple[str, ...]
    function_response_field_order: tuple[str, ...]
    declaration_field_order: tuple[str, ...]
    generation_field_order: tuple[str, ...]
    system_role: str
    tool_schema_field: str


def parse_gemini_policy(raw, location: str) -> GeminiBodyPolicy:
    orders = {
        "field_order": {"contents", "systemInstruction", "tools", "generationConfig"},
        "content_field_order": {"parts", "role"},
        "part_field_order": {"text", "functionCall", "functionResponse", "thoughtSignature"},
        "function_call_field_order": {"id", "name", "args"},
        "function_response_field_order": {"id", "name", "response"},
        "declaration_field_order": {"name", "description"},
        "generation_field_order": {"temperature", "maxOutputTokens", "thinkingConfig"},
    }
    fields = {*orders, "strategy", "system_role", "tool_schema_field"}
    if (not isinstance(raw, dict) or set(raw) != fields
            or raw["strategy"] != "gemini-cli-generate-content"
            or raw["system_role"] not in ("user", "model")
            or raw["tool_schema_field"] not in ("parameters", "parametersJsonSchema")):
        raise ConfigError("invalid_profile", "Invalid Gemini Body policy", location)
    parsed = {}
    for field, required in orders.items():
        order = raw[field]
        if (not isinstance(order, list) or any(not isinstance(x, str) or not x for x in order)
                or len(set(order)) != len(order) or not required <= set(order)):
            raise ConfigError("invalid_profile", "Invalid Gemini field order", location)
        parsed[field] = tuple(order)
    if raw["tool_schema_field"] not in parsed["declaration_field_order"]:
        raise ConfigError("invalid_profile", "Missing Gemini schema field", location)
    return GeminiBodyPolicy(**parsed, system_role=raw["system_role"],
                            tool_schema_field=raw["tool_schema_field"])


def validate_gemini_overrides(overrides, location="extra_body") -> None:
    for field in ("contents", "systemInstruction", "tools"):
        if field in overrides:
            raise ConfigError("profile_owned_body", "Gemini structural fields are Profile-owned",
                              f"{location}.{field}")


def _ordered(value: dict, order: tuple[str, ...]) -> dict:
    return {**{k: value[k] for k in order if k in value},
            **{k: v for k, v in value.items() if k not in order}}


def project_gemini_body(policy: GeminiBodyPolicy, payload: dict) -> dict:
    body = deepcopy(payload)

    def content(value):
        parts = []
        for part in value.get("parts", []):
            if not isinstance(part, dict):
                parts.append(part)
                continue
            if isinstance(part.get("functionCall"), dict):
                part["functionCall"] = _ordered(part["functionCall"],
                                                policy.function_call_field_order)
            if isinstance(part.get("functionResponse"), dict):
                part["functionResponse"] = _ordered(part["functionResponse"],
                                                    policy.function_response_field_order)
            # User/media serialization also accepts the original Gemini snake-case spelling.
            if "inline_data" in part and "inlineData" not in part:
                part["inlineData"] = part.pop("inline_data")
            inline = part.get("inlineData")
            if isinstance(inline, dict) and "mime_type" in inline and "mimeType" not in inline:
                inline["mimeType"] = inline.pop("mime_type")
            parts.append(_ordered(part, policy.part_field_order))
        value["parts"] = parts
        return _ordered(value, policy.content_field_order)

    if isinstance(body.get("systemInstruction"), dict):
        body["systemInstruction"]["role"] = policy.system_role
        body["systemInstruction"] = content(body["systemInstruction"])
    body["contents"] = [content(x) for x in body.get("contents", [])]
    for group in body.get("tools", []):
        if "functionDeclarations" in group:
            group["functionDeclarations"] = [
                _ordered(d, policy.declaration_field_order) for d in group["functionDeclarations"]
            ]
    if isinstance(body.get("generationConfig"), dict):
        body["generationConfig"] = _ordered(body["generationConfig"], policy.generation_field_order)
    return _ordered(body, policy.field_order)
