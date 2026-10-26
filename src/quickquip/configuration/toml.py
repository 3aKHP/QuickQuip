"""Localized, style-preserving TOML document updates."""

from copy import deepcopy
import re
import tomllib

import tomlkit
from tomlkit.container import OutOfOrderTableProxy
from tomlkit.items import AoT, Array, Comment, InlineTable, Null, Table

from quickquip.configuration.merge import same
from quickquip.configuration.errors import ConfigError

# Encoded JSON values use inline tables when embedded in business TOML.
TAG = "__quickquip_value__"


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


def _move_header_comments(owner, end, table):
    if "\n" in table.trivia.indent:
        return
    start = end
    while (
        start and owner.body[start - 1][0] is None and isinstance(owner.body[start - 1][1], Comment)
    ):
        start -= 1
    if start == end:
        return
    table.trivia.indent = (
        "".join(item.as_string() for _, item in owner.body[start:end]) + table.trivia.indent
    )
    # Keep indexed keys in place: comments are unkeyed AST entries.
    for index in range(start, end):
        owner._body[index] = (None, Null())


def _attach_aot_comments(container, array):
    owners = container._tables if isinstance(container, OutOfOrderTableProxy) else [container]
    for owner in owners:
        owner = owner.value if isinstance(owner, Table) else owner
        for index, (_, item) in enumerate(owner.body):
            if item is array:
                _move_header_comments(owner, index, array[0])
                break
    for index in range(1, len(array)):
        owner = array[index - 1].value
        # A comment before the next array header can live in the last nested table.
        while owner.body:
            last = owner.body[-1][1]
            if isinstance(last, Table):
                owner = last.value
            elif isinstance(last, AoT) and last:
                owner = last[-1].value
            else:
                break
        _move_header_comments(owner, len(owner.body), array[index])


def _assign(container, key, value, *, inline=False):
    if key not in container:
        container[key] = _inline(value) if inline else _item(value)
        return
    previous = (
        container.item(key)
        if hasattr(container, "item")
        else container._internal_container.item(key)
    )
    if isinstance(previous, AoT) and previous and not same(previous.unwrap(), value):
        _attach_aot_comments(container, previous)
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
    if same(node.unwrap() if hasattr(node, "unwrap") else node, value):
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
        if same(parse(original, ""), value):
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
    if not same(parse(result, ""), value):
        raise ConfigError("invalid_workspace", "TOML serialization changed configuration values")
    return result
