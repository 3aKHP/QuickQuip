"""search_skill_resources：已激活 Skill 目录内的纯 Python 文本检索。

不起子进程、无注入面、跨平台：匹配用 ``regex`` 模块实现（调用级超时
可中断回溯，配合静态形态检查与墙钟预算构成防 ReDoS 三层防御），字面
量路径复用 ``re.escape``。默认字面量、大小写不敏感；``is_regex=true``
时按正则。命中以 ``file:line`` 返回并带 ±1 行上下文；结果数与输出字节
分别按 ``search_max_results`` / ``search_max_output_bytes`` 截断。
遍历范围 = 扫描时编入清单的安全资源（符号链接与不安全路径已被排除），
每个文件读取前再过一次 ``resolve_skill_file`` 同款加固。
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping

import regex

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
    "为防灾难性回溯，含嵌套量词或交叠分支的量化组、相邻可空量化原子链等"
    "病态正则形态会被静态检查拒绝，漏网形态受引擎超时与时间预算兜底——"
    "被拒之模式请改用字面搜索（is_regex=false）或改写。"
)

TOOL_KEYWORDS = ["skill", "技能", "搜索", "检索", "查找", "grep", "search", "关键词"]

# 单文件检索读取上限：超出只检索前段并标注，防超大资产撑爆内存。
_SEARCH_FILE_READ_CAP_BYTES = 1024 * 1024
_MAX_QUERY_CHARS = 200

# 单次正则匹配的引擎级超时（秒）。regex 模块在 search(string, timeout=)
# 调用级于回溯引擎内周期检查该值，超时抛内置 TimeoutError 真正中断回溯
# ——这是防御纵深的核心层：病态模式最坏只损失本上限的执行时间，而不
# 是冻结整个事件循环（stdlib re 的回溯在 C 层持有 GIL 且不可中断，
# to_thread 也救不了；regex 引擎对部分经典形态有优化，但不免疫全部）。
_REGEX_MATCH_TIMEOUT_S = 1.0
# 单次检索调用的总墙钟预算（秒）：防"每行都不超时但行数多"的累积慢；
# 超时停止扫描并返回已得部分结果。
_SEARCH_TIME_BUDGET_S = 4.0

_QUANTIFIER_RE = re.compile(r"\{(?:\d+(?:,\d*)?|,\d+)\}")
# 静态检查的总量化符上限：正常查询远低于此；相邻可空量词链需要大量
# 量词叠加才能进入指数/组合爆炸区。
_MAX_TOTAL_QUANTIFIERS = 20

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
    flags = 0 if case_sensitive else regex.IGNORECASE
    try:
        pattern = regex.compile(query if is_regex else re.escape(query), flags)
    except regex.error as exc:
        return LLMToolOutput(content=f"正则表达式无效：{exc}", is_error=True)

    max_results = max(1, max_results)
    max_output_bytes = max(1, max_output_bytes)

    hit_blocks: list[str] = []
    hit_count = 0
    stopped_early = False
    timed_out = False
    skipped_binary = 0
    skipped_unreadable = 0
    oversized_files = 0
    deadline = time.monotonic() + _SEARCH_TIME_BUDGET_S

    for resource in skill.resources:
        if hit_count >= max_results:
            stopped_early = True
            break
        if timed_out:
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
            if time.monotonic() > deadline:
                timed_out = True
                break
            try:
                matched = pattern.search(line, timeout=_REGEX_MATCH_TIMEOUT_S)
            except TimeoutError:
                return LLMToolOutput(
                    content=(
                        f"正则匹配超时（{_REGEX_MATCH_TIMEOUT_S:g}s 上限），该模式可能在"
                        "逐行检索中产生灾难性回溯；请改用字面搜索（is_regex=false）"
                        "或改写为更简单的形态。"
                    ),
                    is_error=True,
                )
            if not matched:
                continue
            hit_count += 1
            hit_blocks.append(_format_hit(resource.path, lines, index))
            if hit_count >= max_results:
                # 未穷完搜索空间，保守声明还有更多命中。
                stopped_early = True
                break

    if hit_count == 0 and timed_out:
        return (
            f'[skill_search name="{skill.name}" query="{query}"]\n'
            f"检索超时（{_SEARCH_TIME_BUDGET_S:g}s 预算耗尽），未能完成全部资源扫描。"
        )

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
    if timed_out:
        footer.append("（检索超时，仅显示已扫描部分）")
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
    __slots__ = (
        "start",
        "has_quantifier",
        "branches",
        "current",
        "last_atom_end",
        "last_atom_nullable",
        "pending_adjacent",
        "pending_universal",
        "nullable_run",
        "run_has_universal",
    )

    def __init__(self, start: int = 0) -> None:
        self.start = start
        self.has_quantifier = False
        self.branches: list[str] = []
        self.current = ""
        # 相邻可空量化原子链追踪：last_atom_* 记录上一个原子的边界与可空
        # 性，pending_* 在该原子的量词被消费时结算，nullable_run 为当前
        # 连续链长。run_has_universal 标记链中是否含全能原子。
        self.last_atom_end = -1
        self.last_atom_nullable = False
        self.pending_adjacent = False
        self.pending_universal = False
        self.nullable_run = 0
        self.run_has_universal = False


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


# 全能原子：能匹配（几乎）任意输入。相邻的可空量化全能原子可对同一片
# 输入做组合分割（C(len, n) 随链长指数增长），是灾难性回溯的主形态
# （生产实证形态即 `.*.*.*.*z`）。
_UNIVERSAL_ATOMS = frozenset({".", r"\s", r"\S", r"[\s\S]", r"[\S\s]", r"[^]"})


def _is_universal_atom(atom_text: str) -> bool:
    return atom_text in _UNIVERSAL_ATOMS


def _nullable_quantifier(query: str, start: int) -> bool:
    """该量词是否可匹配零次（``*``、``?``、``{0,...}``、``{,n}``）。"""
    char = query[start]
    if char in "*?":
        return True
    if char == "+":
        return False
    match = _QUANTIFIER_RE.match(query, start)
    if match is None:
        return False
    body = match.group(0)[1:-1]  # "{m,n}" -> "m,n"
    lower = ""
    for digit in body:
        if not digit.isdigit():
            break
        lower += digit
    return not lower or int(lower) == 0


def _register_atom(
    frame: _RegexGroupFrame, query: str, atom_start: int, atom_end: int
) -> None:
    """登记一个刚消费完的原子：结算与上一可空量化原子的相邻性并重置可空态。"""
    frame.pending_adjacent = (
        frame.last_atom_end == atom_start and frame.last_atom_nullable
    )
    frame.last_atom_end = atom_end
    frame.last_atom_nullable = False
    frame.pending_universal = _is_universal_atom(query[atom_start:atom_end])


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

    盯四类高危结构——带量词后缀的组体内再含量词（``(x+x+)+``）、带量词
    后缀的组顶层交替分支相互交叠（``(a|a)*``、``(a|ab)*``）、相邻的可空
    量化原子链（``.*.*.*z``、``a?a?a?b``；含全能原子的两连即拒）、以及
    量化符总数超过上限。解析遇到不认识或畸形的结构时返回 ``None`` 交由
    引擎的错误路径处理；本检查永不抛出异常。静态检查本质是已知形态的
    黑名单，漏网形态由 regex 引擎的匹配超时兜底。
    """
    frames: list[_RegexGroupFrame] = []
    top = _RegexGroupFrame()
    index = 0
    length = len(query)
    total_quantifiers = 0
    while index < length:
        char = query[index]
        frame = frames[-1] if frames else top
        if char == "\\":
            atom_start = index
            frame.current += query[index : index + 2]
            index += 2
            _register_atom(frame, query, atom_start, index)
            continue
        if char == "[":
            atom_start = index
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
            _register_atom(frame, query, atom_start, index)
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
                atom_start = index
                frame.current += query[index:body_start]
                index = body_start
                _register_atom(frame, query, atom_start, index)
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
            # 组作为 parent 的一个原子登记，但保守不参与可空量化链的
            # 延续（组内交叠形态已由前两条规则捕获）。
            parent.pending_adjacent = False
            parent.pending_universal = False
            parent.last_atom_end = close_end
            parent.last_atom_nullable = False
            index = close_end
            continue
        if char == "|":
            frame.branches.append(frame.current)
            frame.current = ""
            frame.nullable_run = 0
            frame.run_has_universal = False
            index += 1
            continue
        quantifier_end = _quantifier_span(query, index)
        if quantifier_end is not None:
            total_quantifiers += 1
            if total_quantifiers > _MAX_TOTAL_QUANTIFIERS:
                return "量化符总数超过上限"
            frame.has_quantifier = True
            frame.current += query[index:quantifier_end]
            nullable = _nullable_quantifier(query, index)
            if nullable:
                if frame.pending_adjacent:
                    frame.nullable_run += 1
                    frame.run_has_universal = (
                        frame.run_has_universal or frame.pending_universal
                    )
                else:
                    frame.nullable_run = 1
                    frame.run_has_universal = frame.pending_universal
                if frame.nullable_run >= 2 and frame.run_has_universal:
                    return "相邻的可空量化全能原子链"
                if frame.nullable_run >= 4:
                    return "连续可空量化原子链"
            else:
                frame.nullable_run = 0
                frame.run_has_universal = False
            frame.last_atom_end = quantifier_end
            frame.last_atom_nullable = nullable
            index = quantifier_end
            continue
        atom_start = index
        frame.current += char
        index += 1
        _register_atom(frame, query, atom_start, index)
    return None
