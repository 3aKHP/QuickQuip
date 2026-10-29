"""JSON-value encoding and localized, style-preserving TOML updates."""

import math
import re

from quickquip.configuration.toml import TAG, parse, render_table
from quickquip.llm.config_errors import ConfigError


def encode(value):
    if value is None:
        return {TAG: "null"}
    if type(value) is int and not -(2**63) <= value < 2**63:
        return {TAG: "integer", "decimal": str(value)}
    if isinstance(value, dict):
        if TAG in value:
            return {
                TAG: "object",
                "entries": [{"key": key, "value": encode(item)} for key, item in value.items()],
            }
        return {key: encode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [encode(item) for item in value]
    return value


def decode(value):
    if isinstance(value, dict):
        if TAG not in value:
            return {key: decode(item) for key, item in value.items()}
        if value == {TAG: "null"}:
            return None
        if set(value) == {TAG, "decimal"} and value[TAG] == "integer":
            number = value["decimal"]
            if isinstance(number, str) and re.fullmatch(r"0|-?[1-9][0-9]*", number):
                return int(number)
        if set(value) == {TAG, "entries"} and value[TAG] == "object":
            entries = value["entries"]
            if isinstance(entries, list):
                result = {}
                for entry in entries:
                    if (
                        not isinstance(entry, dict)
                        or set(entry) != {"key", "value"}
                        or not isinstance(entry["key"], str)
                        or entry["key"] in result
                    ):
                        break
                    result[entry["key"]] = decode(entry["value"])
                else:
                    return result
        raise ConfigError("invalid_workspace", "Invalid tagged configuration value")
    if isinstance(value, list):
        return [decode(item) for item in value]
    if type(value) not in (str, bool, int, float) or (
        type(value) is float and not math.isfinite(value)
    ):
        raise ConfigError("invalid_workspace", "Value must belong to the JSON configuration types")
    return value


def load_value(content: bytes, name: str):
    data = parse(content, name)
    if set(data) != {"value"}:
        raise ConfigError("invalid_workspace", "Configuration file requires a value root", name)
    try:
        return decode(data["value"])
    except ConfigError as exc:
        exc.field_path = name
        raise


def render_value(value, original: bytes | None = None) -> bytes:
    return render_table({"value": encode(value)}, original)
