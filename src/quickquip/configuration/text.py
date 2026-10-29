"""Structured text parsing and localized edits, without expanding environment references."""

from io import StringIO
import json
from pathlib import PurePosixPath
import re
import tomllib

from dotenv.parser import parse_stream
import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

from quickquip.configuration.errors import ConfigError
from quickquip.configuration.toml import render_table
from quickquip.configuration.merge import same


def kind(name):
    if name == ".env" or name.endswith(".env"):
        return "env"
    return PurePosixPath(name).suffix.lstrip(".")


def parse(name, content):
    try:
        text = content.decode("utf-8")
        syntax = kind(name)
        if syntax == "toml":
            return tomllib.loads(text)
        if syntax == "json":
            return json.loads(text)
        if syntax in ("yml", "yaml"):
            return yaml.safe_load(text)
        if syntax == "env":
            result = {}
            for binding in parse_stream(StringIO(text)):
                if binding.error:
                    raise ValueError("invalid dotenv")
                if binding.key is not None:
                    result.setdefault(binding.key, []).append(binding.value)
            return result
        return text
    except (ValueError, UnicodeError, yaml.YAMLError):
        raise ConfigError("invalid_configuration", "Configuration text is invalid", name) from None


def _env_value(key, value, previous=""):
    if value is None:
        return key + "\n"
    # JSON quoting is compatible with dotenv double quotes and keeps raw ${references}.
    rendered = f"{key}={json.dumps(value, ensure_ascii=False)}"
    quote, escape, comment = None, False, ""
    for index, char in enumerate(previous.rstrip("\r\n")):
        if escape:
            escape = False
        elif char == "\\" and quote == '"':
            escape = True
        elif char in "\"'":
            quote = None if quote == char else char if quote is None else quote
        elif char == "#" and quote is None and (index == 0 or previous[index - 1].isspace()):
            comment = " " + previous[index:].rstrip("\r\n")
            break
    if previous.lstrip().startswith("export "):
        rendered = "export " + rendered
    return rendered + comment + ("\r\n" if previous.endswith("\r\n") else "\n")


def render_env(value, original):
    bindings = list(parse_stream(StringIO(original.decode("utf-8"))))
    old = parse(".env", original)
    seen, result = set(), []
    for binding in bindings:
        key, raw = binding.key, binding.original.string
        if key is None:
            result.append(raw)
        elif key not in value:
            continue
        elif same(old[key], value[key]):
            result.append(raw)
            seen.add(key)
        elif key not in seen:
            result.extend(
                _env_value(key, item, raw if index == 0 else "")
                for index, item in enumerate(value[key])
            )
            seen.add(key)
    for key in value:
        if key in seen:
            continue
        if result and not result[-1].endswith("\n"):
            result.append("\n")
        result.extend(_env_value(key, item) for item in value[key])
    return "".join(result).encode("utf-8")


def _yaml_dump(value):
    result = yaml.safe_dump(value, allow_unicode=True, default_flow_style=True, width=100000)
    return result.removesuffix("...\n").rstrip("\n")


def render_yaml(value, original):
    text = original.decode("utf-8")
    node = yaml.compose(text)
    previous = yaml.safe_load(text)
    edits = []

    def patch(current, old, new):
        if same(old, new):
            return
        if (
            isinstance(current, MappingNode)
            and isinstance(old, dict)
            and isinstance(new, dict)
            and not current.flow_style
        ):
            # String keys such as "true" must keep their declared YAML type.
            nodes = {
                (key.value if key.tag.endswith(":str") else yaml.safe_load(key.value)): (key, child)
                for key, child in current.value
            }
            if set(nodes) != set(old):
                edits.append((current.start_mark.index, current.end_mark.index, _yaml_dump(new)))
                return
            for key in old:
                key_node, child = nodes[key]
                if key in new:
                    patch(child, old[key], new[key])
                else:
                    start = text.rfind("\n", 0, key_node.start_mark.index) + 1
                    end = text.find("\n", child.end_mark.index)
                    edits.append((start, len(text) if end < 0 else end + 1, ""))
            additions = {key: item for key, item in new.items() if key not in old}
            if additions:
                indent = current.value[0][0].start_mark.column if current.value else 0
                rendered = yaml.safe_dump(additions, allow_unicode=True, sort_keys=False)
                rendered = "".join(" " * indent + line + "\n" for line in rendered.splitlines())
                position = current.end_mark.index
                prefix = "" if position == 0 or text[position - 1] == "\n" else "\n"
                edits.append((position, position, prefix + rendered))
        elif isinstance(current, SequenceNode) and isinstance(old, list) and isinstance(new, list):
            if len(old) == len(new) and not current.flow_style:
                for child, before, after in zip(current.value, old, new):
                    patch(child, before, after)
            else:
                edits.append((current.start_mark.index, current.end_mark.index, _yaml_dump(new)))
        else:
            rendered = _yaml_dump(new)
            if isinstance(current, ScalarNode) and isinstance(new, str):
                if current.style in ("'", '"'):
                    rendered = yaml.safe_dump(
                        new, allow_unicode=True, default_style=current.style
                    ).rstrip("\n")
            edits.append((current.start_mark.index, current.end_mark.index, rendered))

    if node is None:
        return yaml.safe_dump(value, allow_unicode=True, sort_keys=False).encode()
    patch(node, previous, value)
    boundary = len(text) + 1
    for start, end, replacement in sorted(edits, reverse=True):
        if end > boundary:
            raise ConfigError("configuration_conflict", "Overlapping YAML aliases require editing")
        text = text[:start] + replacement + text[end:]
        boundary = start
    result = text.encode("utf-8")
    if not same(parse("file.yaml", result), value):
        raise ConfigError("configuration_conflict", "YAML edit requires manual reconciliation")
    return result


def render(name, value, original):
    if same(parse(name, original), value):
        return original
    syntax = kind(name)
    if syntax == "toml":
        return render_table(value, original)
    if syntax == "env":
        return render_env(value, original)
    if syntax in ("yaml", "yml"):
        return render_yaml(value, original)
    if syntax == "json":
        match = re.search(r"\n([ \t]+)\S", original.decode("utf-8"))
        indent = match[1] if match else None
        result = json.dumps(value, ensure_ascii=False, indent=indent)
        return (result + ("\n" if original.endswith(b"\n") else "")).encode("utf-8")
    return value.encode("utf-8")
