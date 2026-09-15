"""read_skill_resource：读取已激活 Skill 根内的单个文件（UTF-8 文本）。

路径加固与 catalog.resolve_skill_file 同款：拒绝 ``..``、绝对路径、
反斜杠与符号链接逃逸；内容上限 ``resource_max_bytes``（默认 64KiB），
超限按 UTF-8 安全边界截断并附截断说明。可选 start_line/end_line 行段
参数用于分块读取大文件。文件 I/O 有界（≤ 上限 + 1 字节探测），
不把宿主机绝对路径泄漏进工具结果。
"""

from __future__ import annotations

from collections.abc import Mapping

from quickquip.llm.skills.catalog import (
    LoadedSkill,
    resolve_skill_file,
    utf8_safe_boundary,
)
from quickquip.llm.skills.state import SkillActivationState
from quickquip.llm.skills.tools.activate import require_active_skill
from quickquip.llm.tools import LLMToolOutput, LLMToolSpec

READ_SKILL_RESOURCE_TOOL_NAME = "read_skill_resource"

TOOL_DESCRIPTION = (
    "读取当前会话已激活 Skill 目录内的单个文件（UTF-8 文本，如 references/ "
    "下的参考资料）。path 为 skill 相对路径（例如 references/index.md），"
    "拒绝绝对路径与 .. 穿越；内容大小受部署上限控制，超限只返回前段。"
    "可先用 search_skill_resources 检索定位，或用 start_line/end_line 分块读取。"
)

TOOL_KEYWORDS = ["skill", "技能", "资源", "读取", "文件", "reference", "read", "参考资料"]

READ_SKILL_RESOURCE_SPEC = LLMToolSpec(
    name=READ_SKILL_RESOURCE_TOOL_NAME,
    description=TOOL_DESCRIPTION,
    input_schema={
        "type": "object",
        "properties": {
            "skill": {"type": "string", "description": "已激活的 Skill 名。"},
            "path": {
                "type": "string",
                "description": "skill 相对 POSIX 路径，例如 references/index.md。",
            },
            "start_line": {
                "type": "integer",
                "description": "可选，起始行（1 起，含）。",
            },
            "end_line": {
                "type": "integer",
                "description": "可选，结束行（1 起，含）。",
            },
        },
        "required": ["skill", "path"],
    },
)


def read_skill_resource(
    *,
    skill_name: str,
    path: str,
    skills: Mapping[str, LoadedSkill],
    state: SkillActivationState,
    scope: str,
    max_bytes: int,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str | LLMToolOutput:
    resolved_skill = require_active_skill(skill_name, skills=skills, state=state, scope=scope)
    if isinstance(resolved_skill, LLMToolOutput):
        return resolved_skill
    skill = resolved_skill

    if start_line is not None and start_line < 1:
        return LLMToolOutput(content="start_line 必须是 ≥ 1 的整数。", is_error=True)
    if end_line is not None and end_line < 1:
        return LLMToolOutput(content="end_line 必须是 ≥ 1 的整数。", is_error=True)
    if start_line is not None and end_line is not None and start_line > end_line:
        return LLMToolOutput(content="start_line 必须 ≤ end_line。", is_error=True)

    try:
        absolute = resolve_skill_file(skill, path)
    except ValueError as exc:
        return LLMToolOutput(content=str(exc), is_error=True)

    cap = max(1, max_bytes)
    try:
        with absolute.open("rb") as handle:
            raw = handle.read(cap + 1)
    except OSError as exc:
        return LLMToolOutput(
            content=f'Skill 资源 "{path}" 读取失败（{exc.strerror or exc}）。',
            is_error=True,
        )
    capped = len(raw) > cap
    if capped:
        raw = raw[: utf8_safe_boundary(raw, cap)]
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return LLMToolOutput(
            content=(
                f'Skill 资源 "{path}" 不是有效 UTF-8 文本，无法按文本资源读取；'
                "二进制资产已在 activate_skill 的资源清单中披露。"
            ),
            is_error=True,
        )

    lines = text.split("\n")
    start = start_line if start_line is not None else 1
    end = end_line if end_line is not None else len(lines)
    sliced = "\n".join(lines[start - 1:end])

    notes: list[str] = []
    if capped:
        notes.append(f"[已截断：资源超过 {cap} 字节上限，仅显示前段]")
    if start > 1 or end < len(lines):
        notes.append(f"[第 {start}-{min(end, len(lines))} 行，共 {len(lines)} 行]")
    body = f'[skill_resource name="{skill.name}" path="{path}"]\n{sliced}'
    if notes:
        body = f"{body}\n" + "\n".join(notes)
    return body
