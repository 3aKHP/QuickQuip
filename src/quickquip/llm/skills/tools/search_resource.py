"""search_skill_resources：已激活 Skill 目录内的纯 Python 文本检索。

不起子进程：用标准库 ``re`` 实现（无注入面、跨平台）。默认字面量、
大小写不敏感；``is_regex=true`` 时按正则。命中以 ``file:line`` 返回并带
±1 行上下文；结果数与输出字节分别按 ``search_max_results`` /
``search_max_output_bytes`` 截断。遍历范围 = 扫描时编入清单的安全资源
（符号链接与不安全路径已被排除），每个文件读取前再过一次
``resolve_skill_file`` 同款加固。
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from quickquip.llm.skills.catalog import LoadedSkill, resolve_skill_file
from quickquip.llm.skills.state import SkillActivationState
from quickquip.llm.skills.tools.activate import require_active_skill
from quickquip.llm.tools import LLMToolOutput, LLMToolSpec

SEARCH_SKILL_RESOURCES_TOOL_NAME = "search_skill_resources"

TOOL_DESCRIPTION = (
    "在当前会话已激活的 Skill 目录内搜索文本。默认按字面量、大小写不敏感；"
    "is_regex=true 时按正则表达式匹配。返回 file:line 命中及前后各 1 行"
    "上下文，命中数与输出体积受部署上限截断。适合命令、报错信息、精确术语"
    "等关键词型定位；找到后用 read_skill_resource 读取完整段落。"
    "为防灾难性回溯，含嵌套量词或交叠分支的量化组等病态正则形态会被"
    "拒绝——被拒之模式请改用字面搜索（is_regex=false）或改写。"
)

TOOL_KEYWORDS = ["skill", "技能", "搜索", "检索", "查找", "grep", "search", "关键词"]

# 单文件检索读取上限：超出只检索前段并标注，防超大资产撑爆内存。
_SEARCH_FILE_READ_CAP_BYTES = 1024 * 1024
_MAX_QUERY_CHARS = 200

_QUANTIFIER_RE = re.compile(r"\{(?:\d+(?:,\d*)?|,\d+)\}")

SEARCH_SKILL_RESOURCES_SPEC = LLMToolSpec(
    name=SEARCH_SKILL_RESOURCES_TOOL_NAME,
    description=TOOL_DESCRIPTION,
    input_schema={
        "type": "object",
        "properties": {
            "skill": {"type": "string", "description": "已激活的 Skill 名。"},
            "query": {"type": "string", "description": "检索词（默认字面量）。"},
            "is_regex": {
                "type": "boolean",
                "description": "true 时 query 按正则表达式解释（默认 false 字面量）。",
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "true 时大小写敏感（默认 false 不敏感）。",
            },
        },
        "required": ["skill", "query"],
    },
)


def search_skill_resources(
    *,
    skill_name: str,
    query: str,
    skills: Mapping[str, LoadedSkill],
    state: SkillActivationState,
    scope: str,
    is_regex: bool = False,
    case_sensitive: bool = False,
    max_results: int = 50,
    max_output_bytes: int = 32768,
) -> str | LLMToolOutput:
    resolved_skill = require_active_skill(skill_name, skills=skills, state=state, scope=scope)
    if isinstance(resolved_skill, LLMToolOutput):
        return resolved_skill
    skill = resolved_skill

    if not query.strip():
        return LLMToolOutput(content="query 不能为空。", is_error=True)
    if len(query) > _MAX_QUERY_CHARS:
        return LLMToolOutput(
            content=f"query 超过 {_MAX_QUERY_CHARS} 字符上限。", is_error=True
        )
    if is_regex:
        reason = _find_pathological_regex(query)
        if reason is not None:
            return LLMToolOutput(
                content=(
                    f"正则形态不被允许（{reason}），可能在逐行检索中产生灾难性回溯；"
                    "请改用字面搜索（is_regex=false）或改写为无嵌套量词、无交叠分支的形态。"
                ),
                is_error=True,
            )
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        pattern = re.compile(query if is_regex else re.escape(query), flags)
    except re.error as exc:
        return LLMToolOutput(content=f"正则表达式无效：{exc}", is_error=True)

    max_results = max(1, max_results)
    max_output_bytes = max(1, max_output_bytes)

    hit_blocks: list[str] = []
    hit_count = 0
    stopped_early = False
    skipped_binary = 0
    skipped_unreadable = 0
    oversized_files = 0

    for resource in skill.resources:
        if hit_count >= max_results:
            stopped_early = True
            break
        try:
            absolute = resolve_skill_file(skill, resource.path)
            with absolute.open("rb") as handle:
                raw = handle.read(_SEARCH_FILE_READ_CAP_BYTES + 1)
        except (ValueError, OSError):
            skipped_unreadable += 1
            continue
        file_capped = len(raw) > _SEARCH_FILE_READ_CAP_BYTES
        if file_capped:
            raw = raw[:_SEARCH_FILE_READ_CAP_BYTES]
            oversized_files += 1
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            skipped_binary += 1
            continue
        lines = text.split("\n")
        for index, line in enumerate(lines):
            if not pattern.search(line):
                continue
            hit_count += 1
            hit_blocks.append(_format_hit(resource.path, lines, index))
            if hit_count >= max_results:
                # 未穷完搜索空间，保守声明还有更多命中。
                stopped_early = True
                break

    if hit_count == 0:
        notes = []
        if skipped_binary:
            notes.append(f"（跳过 {skipped_binary} 个非 UTF-8 文件）")
        suffix = " " + " ".join(notes) if notes else ""
        return (
            f'[skill_search name="{skill.name}" query="{query}"]\n'
            f"没有命中。{suffix}"
        )

    header = f'[skill_search name="{skill.name}" query="{query}" matches={hit_count}]'
    body_parts = [header]
    output_capped = False
    for block in hit_blocks:
        candidate = "\n\n".join([*body_parts, block])
        if len(candidate.encode("utf-8")) > max_output_bytes:
            output_capped = True
            break
        body_parts.append(block)

    footer: list[str] = []
    shown = len(body_parts) - 1
    if output_capped or stopped_early:
        footer.append(f"（命中较多，仅显示前 {shown} 处）")
    if skipped_binary:
        footer.append(f"（跳过 {skipped_binary} 个非 UTF-8 文件）")
    if oversized_files:
        footer.append(f"（{oversized_files} 个文件过大，仅检索前 1MiB）")
    if skipped_unreadable:
        footer.append(f"（{skipped_unreadable} 个文件读取失败，已跳过）")
    return "\n\n".join([*body_parts, *footer]) if footer else "\n\n".join(body_parts)


def _format_hit(path: str, lines: list[str], index: int) -> str:
    """单个命中：``path:line:`` 头 + ±1 行上下文，命中行以 ``>`` 标记。"""
    rows = [f"{path}:{index + 1}:"]
    for line_index in range(max(0, index - 1), min(len(lines), index + 2)):
        marker = ">" if line_index == index else " "
        rows.append(f"{marker} {line_index + 1} | {lines[line_index]}")
    return "\n".join(rows)


_INLINE_FLAG_CHARS = frozenset("aiLmsux-")


class _RegexGroupFrame:
    __slots__ = ("start", "has_quantifier", "branches", "current")

    def __init__(self, start: int = 0) -> None:
        self.start = start
        self.has_quantifier = False
        self.branches: list[str] = []
        self.current = ""


def _quantifier_span(query: str, pos: int) -> int | None:
    """``pos`` 处若是一个量词 token，返回其结束位置；``{m,n}`` 需完整匹配才算。"""
    if pos >= len(query):
        return None
    char = query[pos]
    if char in "*+?":
        return pos + 1
    if char == "{":
        match = _QUANTIFIER_RE.match(query, pos)
        if match is not None:
            return match.end()
    return None


def _consume_group_prefix(query: str, index: int) -> tuple[int, bool] | None:
    """解析 ``(`` 处的组头，返回（组体起始位置, 是否为无组体的自包含原子）。

    自包含原子（``(?P=name)``、``(?i)``）不需要入栈；无法识别的形态返回
    ``None`` 表示本检查无意见，交给 ``re.compile`` 判定。
    """
    length = len(query)
    if index + 1 >= length or query[index + 1] != "?":
        return index + 1, False
    rest = query[index + 2 :]
    if rest.startswith("P="):
        close = query.find(")", index + 4)
        if close == -1:
            return None
        return close + 1, True
    if rest.startswith(("<=", "<!")):
        return index + 4, False
    if rest.startswith(("P<", "<")):
        close = query.find(">", index + 2)
        if close == -1:
            return None
        return close + 1, False
    if rest.startswith((":", "=", "!", ">")):
        return index + 3, False
    if rest.startswith("("):
        # 条件组 (?(id)yes|no)：id 部分无嵌套，跳过即可。
        close = query.find(")", index + 3)
        if close == -1:
            return None
        return close + 1, False
    cursor = index + 2
    while cursor < length and query[cursor] in _INLINE_FLAG_CHARS:
        cursor += 1
    if cursor < length and query[cursor] == ":":
        return cursor + 1, False
    if cursor < length and query[cursor] == ")":
        return cursor + 1, True
    return None


def _find_pathological_regex(query: str) -> str | None:
    """走查式静态检查：返回病态形态的原因字符串，良性/无意见返回 ``None``。

    只盯两类高危结构——带量词后缀的组体内再含量词（``(x+x+)+``），以及
    带量词后缀的组顶层交替分支相互交叠（``(a|a)*``、``(a|ab)*``）。解析
    遇到不认识或畸形的结构时返回 ``None`` 交由 ``re.compile`` 的错误路径
    处理；本检查永不抛出异常。
    """
    frames: list[_RegexGroupFrame] = []
    top = _RegexGroupFrame()
    index = 0
    length = len(query)
    while index < length:
        char = query[index]
        frame = frames[-1] if frames else top
        if char == "\\":
            frame.current += query[index : index + 2]
            index += 2
            continue
        if char == "[":
            end = index + 1
            if end < length and query[end] == "^":
                end += 1
            if end < length and query[end] == "]":
                end += 1
            while end < length and query[end] != "]":
                end += 2 if query[end] == "\\" else 1
            end = min(end + 1, length)
            frame.current += query[index:end]
            index = end
            continue
        if char == "(":
            if query.startswith("(?#", index):
                close = query.find(")", index + 3)
                index = length if close == -1 else close + 1
                continue
            consumed = _consume_group_prefix(query, index)
            if consumed is None:
                return None
            body_start, is_bare_atom = consumed
            if is_bare_atom:
                frame.current += query[index:body_start]
                index = body_start
                continue
            frames.append(_RegexGroupFrame(start=index))
            index = body_start
            continue
        if char == ")":
            if not frames:
                return None
            frame = frames.pop()
            suffix_end = _quantifier_span(query, index + 1)
            if suffix_end is not None:
                if frame.has_quantifier:
                    return "量化组内嵌套量词"
                branches = [*frame.branches, frame.current]
                for left in range(len(branches)):
                    for right in range(left + 1, len(branches)):
                        first, second = branches[left], branches[right]
                        if first.startswith(second) or second.startswith(first):
                            return "量化组分支相互交叠"
            close_end = suffix_end if suffix_end is not None else index + 1
            parent = frames[-1] if frames else top
            parent.current += query[frame.start : close_end]
            if frame.has_quantifier or suffix_end is not None:
                parent.has_quantifier = True
            index = close_end
            continue
        if char == "|":
            frame.branches.append(frame.current)
            frame.current = ""
            index += 1
            continue
        quantifier_end = _quantifier_span(query, index)
        if quantifier_end is not None:
            frame.has_quantifier = True
            frame.current += query[index:quantifier_end]
            index = quantifier_end
            continue
        frame.current += char
        index += 1
    return None
