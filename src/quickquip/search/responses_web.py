"""Pinned Codex standalone search command contract and result projection.

Derived from openai/codex 77873dd0d284aeba7ce849b995b28ee8f4498d73,
Apache-2.0. The schema is generated with schemars 0.8.22 and serialized
through codex-tools JsonSchema; metadata absent from that wire type is dropped.
"""

from __future__ import annotations

from copy import deepcopy
from importlib.resources import files
import json
import re
from typing import Any

TOOL_NAME = "web_run"
PROFILE_ID = "codex-relay-standalone-search"
_SCHEMA = json.loads(
    files("quickquip.search").joinpath("responses_web_schema.json").read_text(encoding="utf-8")
)
DESCRIPTION = (
    files("quickquip.search").joinpath("responses_web_description.txt").read_text(encoding="utf-8")
)
MAX_OPERATIONS = 64
MAX_RESULT_BYTES = 24_576


def command_schema() -> dict[str, Any]:
    return deepcopy(_SCHEMA)


def operation_count(commands: dict[str, Any]) -> int:
    return sum(
        len(v) for k, v in commands.items() if k != "response_length" and isinstance(v, list)
    )


def namespace_spec() -> dict[str, Any]:
    return {
        "type": "namespace",
        "name": "web",
        "description": "Tools in the web namespace.",
        "tools": [
            {
                "type": "function",
                "name": "run",
                "description": DESCRIPTION,
                "parameters": command_schema(),
                "strict": False,
            }
        ],
    }


def bound_output(text: str, max_bytes: int = MAX_RESULT_BYTES) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    suffix = "\n[搜索材料已按本地预算截断]"
    return raw[: max(0, max_bytes - len(suffix.encode()))].decode("utf-8", errors="ignore") + suffix


def read_result(body: Any) -> tuple[str, list[dict[str, Any]], bool]:
    if not isinstance(body, dict) or not isinstance(body.get("output"), str):
        raise ValueError("搜索端点缺少明文 output")
    text = body["output"]
    rows = body.get("results") or []
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("搜索端点 results 结构无效")
    failed = (
        bool(body.get("error"))
        or not text.strip()
        or bool(
            re.search(
                r"(?:^|\n)(?:(?:Internal Error|Error) \(\)|Error parsing function call:)",
                text,
            )
        )
    )
    failed = failed or any(
        isinstance(row.get("title"), str) and row["title"] in {"Internal Error", "Error"}
        for row in rows
    )
    failed = failed or any(row.get("type") == "error" for row in rows)
    return text, rows, failed


def validate_commands(commands: Any) -> None:
    """Validate execution independently of the model-facing schema declaration."""

    def check(value: Any, schema: dict, path: str) -> None:
        kind = schema.get("type")
        valid = {
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "string": isinstance(value, str),
            "integer": isinstance(value, int) and not isinstance(value, bool) and value >= 0,
        }.get(kind, False)
        if not valid:
            raise ValueError(f"{path}: 参数类型不正确")
        if "enum" in schema and value not in schema["enum"]:
            raise ValueError(f"{path}: 未知选项")
        if kind == "object":
            properties = schema.get("properties", {})
            if set(value) - set(properties):
                raise ValueError(f"{path}: 未知字段")
            if set(schema.get("required", [])) - set(value):
                raise ValueError(f"{path}: 缺少必填字段")
            for key, item in value.items():
                check(item, properties[key], f"{path}.{key}")
        elif kind == "array":
            for item in value:
                check(item, schema["items"], path)
        elif kind == "string" and not value.strip() and path.rsplit(".", 1)[-1] != "market":
            raise ValueError(f"{path}: 参数不能为空")

    if len(json.dumps(commands, ensure_ascii=False).encode()) > 32_768:
        raise ValueError("搜索参数超过大小上限")
    if isinstance(commands, dict) and any(
        isinstance(value, list) and not value for value in commands.values()
    ):
        raise ValueError("web.run: 操作列表不能为空")
    check(commands, _SCHEMA, "web.run")
    if not operation_count(commands):
        raise ValueError("搜索命令为空")
