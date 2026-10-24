"""JSON-value encoding and localized, style-preserving TOML updates."""

from copy import deepcopy
import math
import re
import tomllib

import tomlkit
from tomlkit.container import OutOfOrderTableProxy
from tomlkit.items import AoT, Array, InlineTable, Table

from quickquip.config_sync.bundle import digest
from quickquip.llm.config_errors import ConfigError

TAG = "__quickquip_value__"


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


def parse(content: bytes, name: str):
    try:
        text = content.decode("utf-8")
        data = tomllib.loads(text)
    except (ValueError, UnicodeError) as exc:
        # Parser messages may contain configuration values; expose location only.
        location = re.search(r"line (\d+), column (\d+)", str(exc))
        raise ConfigError(
            "invalid_toml",
            "Expected UTF-8 TOML 1.0",
            name,
            {"line": int(location[1]), "column": int(location[2])} if location else None,
        ) from None
    return data


def load_value(content: bytes, name: str):
    data = parse(content, name)
    if set(data) != {"value"}:
        raise ConfigError("invalid_workspace", "Configuration file requires a value root", name)
    try:
        return decode(data["value"])
    except ConfigError as exc:
        exc.field_path = name
        raise


def _inline(value):
    if isinstance(value, dict):
        result = tomlkit.inline_table()
        for key, item in value.items():
            result[key] = _inline(item)
        return result
    if isinstance(value, list):
        result = tomlkit.array()
        for item in value:
            result.append(_inline(item))
        return result
    return tomlkit.item(value)


def _item(value):
    if isinstance(value, dict):
        if TAG in value:
            return _inline(value)
        table = tomlkit.table()
        for key, item in value.items():
            table[key] = _item(item)
        return table
    if isinstance(value, list):
        if value and all(isinstance(item, dict) and TAG not in item for item in value):
            array = tomlkit.aot()
            for item in value:
                array.append(_item(item))
            return array
        array = tomlkit.array()
        for item in value:
            # Arrays containing tagged tables use inline tables throughout.
            array.append(_inline(item))
        return array
    if isinstance(value, str):
        return tomlkit.string(
            value, multiline="\n" in value and "\r" not in value and not value.startswith("\n")
        )
    return tomlkit.item(value)


def _identity(items):
    if not items or not all(isinstance(item, dict) for item in items):
        return None
    for keys in (("id",), ("alias",), ("model",), ("provider_id", "model"), ("name",)):
        if all(all(isinstance(item.get(key), str) for key in keys) for item in items):
            identities = [tuple(item[key] for key in keys) for item in items]
            if len(set(identities)) == len(identities):
                return keys
    return None


def _assign(container, key, value, *, inline=False):
    if key not in container:
        container[key] = _inline(value) if inline else _item(value)
        return
    previous = (
        container.item(key)
        if hasattr(container, "item")
        else container._internal_container.item(key)
    )
    updated = _patch(previous, value, inline=inline)
    if updated is previous:
        return
    headers = (Table, AoT, OutOfOrderTableProxy)
    if isinstance(previous, headers) != isinstance(updated, headers):
        # A former child header cannot keep its physical slot when becoming a scalar:
        # after another child header it would attach to that child instead of its parent.
        del container[key]
    container[key] = updated


def _patch(node, value, *, inline=False):
    if digest(node.unwrap() if hasattr(node, "unwrap") else node) == digest(value):
        return node
    if isinstance(node, InlineTable) and isinstance(value, dict):
        for key in list(node):
            if key not in value:
                del node[key]
        for key, item in value.items():
            _assign(node, key, item, inline=True)
        return node
    if isinstance(node, (Table, OutOfOrderTableProxy)) and isinstance(value, dict):
        if isinstance(node, OutOfOrderTableProxy) and not value:
            return _item(value)
        for key in list(node):
            if key not in value:
                del node[key]
        for key, item in value.items():
            _assign(node, key, item)
        if not value:
            # Parsed implicit parents otherwise disappear after their last child is removed.
            node._is_super_table = False
        return node
    if (
        isinstance(node, AoT)
        and isinstance(value, list)
        and value
        and all(isinstance(item, dict) and TAG not in item for item in value)
    ):
        keys = _identity(value)
        old = (
            {
                tuple(item[key] for key in keys): item
                for item in node
                if all(isinstance(item.get(key), str) for key in keys)
            }
            if keys
            else {}
        )
        result = tomlkit.aot()
        for index, item in enumerate(value):
            previous = (
                old.get(tuple(item[key] for key in keys))
                if keys
                else (node[index] if index < len(node) else None)
            )
            result.append(_patch(previous, item) if previous is not None else _item(item))
        return result
    if isinstance(node, Array) and isinstance(value, list):
        for index, item in enumerate(value):
            if index < len(node):
                node[index] = _patch(node.item(index), item, inline=True)
            else:
                node.append(_inline(item))
        while len(node) > len(value):
            del node[-1]
        return node
    result = _inline(value) if inline else _item(value)
    if hasattr(node, "trivia") and hasattr(result, "trivia"):
        result._trivia = deepcopy(node.trivia)
        if isinstance(node, (Table, AoT)) and not isinstance(result, (Table, AoT)):
            result.trivia.trail = "\n"
    return result


def render_table(value: dict, original: bytes | None = None) -> bytes:
    if original is not None:
        if digest(parse(original, "")) == digest(value):
            return original
        document = tomlkit.parse(original.decode("utf-8"))
        for key in list(document):
            if key not in value:
                del document[key]
    else:
        document = tomlkit.document()
    for key, item in value.items():
        _assign(document, key, item)
    result = tomlkit.dumps(document).encode("utf-8")
    if digest(parse(result, "")) != digest(value):
        raise ConfigError("invalid_workspace", "TOML serialization changed configuration values")
    return result


def render_value(value, original: bytes | None = None) -> bytes:
    return render_table({"value": encode(value)}, original)
