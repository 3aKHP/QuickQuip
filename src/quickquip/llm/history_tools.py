"""群聊历史查询工具（#72 实施计划 §6.1/§6.2）：主模型的直接搜索与阅读。

职责：工具 schema、参数校验（群聊限定、启用门控、词项/时间/成员解析）、
结果渲染（命中预览/连续消息 + 来源引用 + 覆盖事实）、结果预算接入与
声明参数白名单。查询本体归 ``chat/history_query.py``；本模块不依赖
NoneBot。

安全边界（§6/§9）：
- 不接受 group_id 参数——群号恒取 ``ToolExecutionContext``；私聊一律拒绝。
- 启用门控双重校验：工具面构建时过滤（不曝光）+ handler 内再验（防绕过）。
- 结果为临时载荷：注册侧声明 ephemeral，落库声明参数走白名单
  （模式/时间范围/引用计数），不存关键词、问题与正文。
- 历史正文按不可信用户内容处理，只作证据；敏感过滤由
  ``tool_result_pipeline`` 对参数与结果统一执行。
"""
from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from quickquip.chat.history_query import (
    ArchivedMessage,
    HistoryQueryService,
    HistorySession,
    QueryStatus,
)
from quickquip.llm.tools import LLMToolSpec
from quickquip.llm.token_estimate import estimate_tokens

# ── 预算初值（实施计划 §8.1；领域常量，实验后按记录调整） ──────────
SEARCH_RESULT_TOKEN_CAP = 1200
READ_RESULT_TOKEN_CAP = 2400
DIRECT_HISTORY_LOOP_BUDGET = 6000
DEFAULT_WINDOW_DAYS = 7
MAX_RANGE_DAYS = 180
READ_RADIUS_DEFAULT = 5
READ_MAX_MESSAGES = 12
PREVIEW_CHARS = 80
RESUME_RESERVE_TOKENS = 512
# 委派调查前，父 Loop 剩余结果空间至少要装得下报告的最小可用部分
MIN_PARENT_REPORT_SPACE = 800

BEIJING_TZ = ZoneInfo("Asia/Shanghai")
"""工具时间语义与轮次信封一致（北京时间）；date-only 输入按此解释。"""

HISTORY_TOOLS = (
    "search_group_history",
    "read_group_history",
    "investigate_group_history",
)

INVESTIGATION_REPORT_TOKEN_CAP = 2000
QUESTION_MAX_CHARS = 2000
CONTEXT_NOTE_MAX_CHARS = 2000
MAX_ANCHORS = 8

INVESTIGATION_BUDGET_REPLY = (
    "剩余结果空间不足以接收调查报告，请基于已获取的内容作答，或下次再问。"
)

# count 结果自身很小，但词项回显与覆盖行需要余量（N02 预算接入）
COUNT_RESULT_TOKEN_CAP = 480
# 单词项长度帽：count 的词项会回显进结果与回执（N02 防参数回显突破预算）
COUNT_TERM_MAX_CHARS = 64

_PRIVATE_CHAT_REPLY = "该工具仅支持群聊使用。"
_DISABLED_REPLY = "本群未开启群聊历史查询，无法执行。"
_BUDGET_REPLY = "本轮群聊历史查询额度已用完，请基于已获取的内容作答。"


@dataclass(slots=True)
class HistoryToolState:
    """请求级历史工具状态：随 ``ToolExecutionContext`` 生命周期存亡。

    - ``session``：游标命名空间（只在当前检索会话内有效）；
    - ``direct_budget_tokens``：直接查询（非调查）的结果累计预算；
    - ``round_space_tokens``：工具循环每轮刷新的"当前请求剩余空间"
      （由 loop 依当前 request 探针写入，工具不自行猜测）。
    """

    session: HistorySession = field(default_factory=HistorySession)
    direct_budget_tokens: int = DIRECT_HISTORY_LOOP_BUDGET
    round_space_tokens: int | None = None
    # 父 Loop 有效性检查（service 侧注入；调查执行器在每次模型活动前调用）
    parent_cancel_check: Callable[[], None] | None = None
    # 「父 Loop 最多委派一次」的当轮事实与既有结果缓存
    investigation_used: bool = False
    investigation_result_text: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def begin_round(self, space_tokens: int | None) -> None:
        with self._lock:
            self.round_space_tokens = space_tokens

    def allowance(self, per_call_cap: int, batch_pending: int) -> int:
        """本次调用可用结果预算 = min(单次帽、Loop 历史余额、当前请求
        剩余空间 − 本批其余调用的最小结果封套)。"""
        with self._lock:
            allowance = min(per_call_cap, self.direct_budget_tokens)
            if self.round_space_tokens is not None:
                reserve = RESUME_RESERVE_TOKENS + batch_pending * 256
                allowance = min(
                    allowance, max(0, self.round_space_tokens - reserve)
                )
            return max(0, allowance)

    def consume(self, tokens: int) -> None:
        with self._lock:
            self.direct_budget_tokens = max(0, self.direct_budget_tokens - tokens)
            if self.round_space_tokens is not None:
                self.round_space_tokens = max(
                    0, self.round_space_tokens - tokens
                )


# ── 时间解析 ────────────────────────────────────────────────────────

def parse_history_time(value: str) -> datetime | None:
    """带时区 ISO 8601 或 ``YYYY-MM-DD``（按北京时间解释）。无效返回 None。"""
    text = str(value).strip()
    if not text:
        return None
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        try:
            return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=BEIJING_TZ)
        except ValueError:
            return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BEIJING_TZ)
    return parsed


def _format_ts(ts: float) -> str:
    moment = datetime.fromtimestamp(ts, tz=BEIJING_TZ)
    return f"{moment:%m-%d %H:%M}"


def _format_coverage(coverage) -> str:
    if coverage is None:
        return "归档覆盖：暂不可知。"
    if coverage.total_messages == 0 or coverage.earliest_ts is None:
        return "归档覆盖：本群暂无归档记录。"
    earliest = datetime.fromtimestamp(coverage.earliest_ts, tz=BEIJING_TZ)
    latest = datetime.fromtimestamp(coverage.latest_ts, tz=BEIJING_TZ)
    return (
        f"归档覆盖：{earliest:%Y-%m-%d} 至 {latest:%Y-%m-%d}，共 "
        f"{coverage.total_messages} 条（归档时间口径，连续性未知，"
        "停机期间可能缺漏）。"
    )


# ── 声明参数白名单（持久化脱敏，§8.2） ───────────────────────────────

def redact_search_arguments(arguments_json: str) -> str:
    """持久化声明只留模式与规范化时间范围；词项/成员不落库。"""
    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        args = {}
    payload: dict[str, Any] = {"mode": "search" if not args.get("cursor") else "continue"}
    for key in ("start", "end"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            payload[key] = value.strip()[:32]
    return json.dumps(payload, ensure_ascii=False)


def redact_count_arguments(arguments_json: str) -> str:
    """count 声明只留模式与时间范围；词项不落库（与 search 同口径）。"""
    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        args = {}
    payload: dict[str, Any] = {"mode": "count"}
    for key in ("start", "end"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            payload[key] = value.strip()[:32]
    return json.dumps(payload, ensure_ascii=False)


def redact_read_arguments(arguments_json: str) -> str:
    """持久化声明只留模式/方向/时间范围与引用计数；锚点正文不落库。"""
    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        args = {}
    if args.get("cursor"):
        payload: dict[str, Any] = {"mode": "continue"}
    elif args.get("anchor"):
        payload = {"mode": "anchor", "anchor_kind": "message_ref"}
    else:
        payload = {"mode": "range"}
    for key in ("start", "end", "direction"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            payload[key] = value.strip()[:32]
    return json.dumps(payload, ensure_ascii=False)


def redact_recent_arguments(arguments_json: str) -> str:
    """search_recent_messages 同属临时结果（ADR-0005）：声明只留模式。"""
    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        args = {}
    return json.dumps(
        {"mode": "recent", "has_query": bool(args.get("query"))},
        ensure_ascii=False,
    )


# ── 工具声明与 handler ──────────────────────────────────────────────

@dataclass(slots=True)
class HistoryToolDeps:
    """历史工具的宿主注入面：不传整只 LLMService，只给必要闭包。"""

    query_service: HistoryQueryService
    is_enabled: Callable[[int | str], bool]
    resolve_speaker: Callable[[int | str, str], list[str]]


def _speaker_line(user_id: str | None, sender_name: str) -> str:
    if user_id:
        return f"{sender_name}（QQ {user_id}）"
    return sender_name


_TRUNCATION_NOTE = "（因结果预算截断，以下内容不完整；可用游标续读。）"


def _clip_line(line: str, budget: int) -> str:
    """按预算裁单行（grapheme 近似：字符二分至估算入帽）。"""
    if estimate_tokens(line) <= budget:
        return line
    low, high = 0, len(line)
    while low < high:
        mid = (low + high + 1) // 2
        if estimate_tokens(line[:mid]) <= budget:
            low = mid
        else:
            high = mid - 1
    return line[:low] + "…"


def _clip_footer(footer: str, budget: int) -> str:
    """footer 超帽时整体裁剪（覆盖信息保头行，其余丢弃）。"""
    if estimate_tokens(footer) <= budget:
        return footer
    first = footer.splitlines()[0] if footer else ""
    clipped = _clip_line(first, max(budget - estimate_tokens(_TRUNCATION_NOTE), 8))
    return clipped


def _trim_to_budget(
    lines: list[str], header: str, footer: str, token_cap: int
) -> tuple[list[str], bool, str]:
    """组装整包并对最终输出执行硬上限（R02）。

    首条、footer、截断提示一律计入：首行超限按可续读片段裁剪而非
    整条保留；footer 超帽截断。返回 (行列表, 是否截断, 最终 footer)。
    """
    if token_cap <= 0:
        return [], False, _clip_footer(footer, 64)
    footer_final = _clip_footer(footer, max(token_cap // 3, 64))
    note_budget = estimate_tokens(_TRUNCATION_NOTE)
    kept: list[str] = []
    trimmed = False
    for line in lines:
        candidate = "\n".join([header, *kept, line, footer_final])
        if estimate_tokens(candidate) > token_cap:
            if not kept:
                # 首行也超限：按剩余预算切成可续读片段（不整条保留）
                reserved = token_cap - estimate_tokens(header) - estimate_tokens(
                    footer_final
                ) - note_budget
                kept.append(_clip_line(line, max(reserved, 16)))
            trimmed = True
            break
        kept.append(line)
    else:
        if estimate_tokens("\n".join([header, *kept, footer_final])) > token_cap:
            trimmed = True
    return kept, trimmed, footer_final


SEARCH_GROUP_HISTORY_SPEC = LLMToolSpec(
    name="search_group_history",
    description=(
        "搜索当前群的已归档历史消息（按时间窗口、可按成员过滤），"
        "返回命中预览与来源引用。适合查「之前谁说过什么」。"
        "时间用 YYYY-MM-DD 或 ISO 8601（北京时间）；缺省查最近 "
        f"{DEFAULT_WINDOW_DAYS} 天，跨度最大 {MAX_RANGE_DAYS} 天。"
        "terms 最多 5 个词项，任一命中即算匹配。"
        "结果含覆盖范围说明；游标 cursor 可向更早方向续查。"
        "只读，不改写任何记录。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "terms": {
                "type": "array",
                "items": {"type": "string"},
                "description": "1-5 个搜索词项，任一命中即算匹配",
            },
            "start": {"type": "string", "description": "起始时间（含），缺省为窗口起点"},
            "end": {"type": "string", "description": "结束时间（不含），缺省为现在"},
            "speaker": {"type": "string", "description": "按成员过滤：QQ 号或名字"},
            "cursor": {"type": "string", "description": "续查上一页返回的游标"},
        },
        "required": [],
    },
)

COUNT_GROUP_HISTORY_SPEC = LLMToolSpec(
    name="count_group_history",
    description=(
        "统计当前群归档窗口内命中任一搜索词的消息总数（全量扫描，"
        "不受常规搜索分页限制）。计数为 0 即这些词在该窗口的已归档、"
        "未撤回可读记录中从未出现（确定性结论，以结果附带的归档覆盖"
        "说明为准——停机缺漏不在归档内；回执引用可直接写进调查报告"
        "的 evidence_refs）；计数 > 0 只证明出现过，定位具体消息仍需 "
        "search_group_history。时间用 YYYY-MM-DD 或 ISO 8601（北京时间）；"
        f"缺省查最近 {DEFAULT_WINDOW_DAYS} 天，跨度最大 {MAX_RANGE_DAYS} 天，"
        "更早区间请分段计数。只读。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "terms": {
                "type": "array",
                "items": {"type": "string"},
                "description": "1-5 个搜索词项，任一命中即算匹配",
            },
            "start": {"type": "string", "description": "起始时间（含）"},
            "end": {"type": "string", "description": "结束时间（不含），缺省为现在"},
        },
        "required": [],
    },
)


INVESTIGATE_GROUP_HISTORY_SPEC = LLMToolSpec(
    name="investigate_group_history",
    description=(
        "把复杂的群历史问题委派给专用调查子任务（独立上下文，多次换词搜索、"
        "翻页、锚点阅读、核对时间线），返回带来源引用与原文证据的结构化报告。"
        "适合：方案为什么变了、最终决定是什么、多方说法核对这类需要跨时段"
        "追查的问题。找某句原话请直接用 search_group_history。"
        "每个回答周期最多委派一次，耗时可达数分钟；question 要写清要查什么、"
        "可选 context 提供待核实的背景，start/end 限定时间窗（北京时间）。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "调查问题（≤2000 字符）：要查证什么、判断标准",
            },
            "context": {
                "type": "string",
                "description": "可选背景（视为待核实线索，不是事实）",
            },
            "start": {"type": "string", "description": "时间窗起点（北京时间）"},
            "end": {"type": "string", "description": "时间窗终点（北京时间）"},
            "anchors": {
                "type": "array",
                "items": {"type": "string"},
                "description": "可选起始来源引用（hr1 开头，≤8 个）",
            },
        },
        "required": [],
    },
)


def render_investigation_result(result, token_cap: int = INVESTIGATION_REPORT_TOKEN_CAP) -> str:
    """把调查结果渲染为主模型可用的有界报告（含程序取回的原文证据）。"""
    status_label = {
        "completed": "完成",
        "partial": "部分完成（预算/时限触顶）",
        "invalid_report": "报告未通过校验（附已读证据）",
        "failed": "执行失败",
        "busy": "并发占用",
    }.get(result.status, result.status)
    header = (
        f"历史调查报告（{status_label}；模型调用 {result.model_calls} 次、"
        f"工具调用 {result.tool_calls} 次、用时 {result.elapsed_seconds:.0f}s）"
    )
    lines: list[str] = []
    for index, finding in enumerate(result.findings, 1):
        lines.append(f"{index}. {finding.claim}")
        for ref in finding.evidence_refs:
            excerpt = result.evidence.get(ref, "（证据原文不可用）")
            lines.append(f"   证据（ref {ref}）：{excerpt}")
    if not lines:
        lines.append("（无结构化结论）")
    footer_parts: list[str] = []
    if result.unresolved:
        footer_parts.append(f"未决：{result.unresolved}")
    if result.suggested_followup:
        footer_parts.append(f"建议后续：{result.suggested_followup}")
    if result.coverage_note:
        footer_parts.append(result.coverage_note)
    if result.detail:
        footer_parts.append(result.detail)
    footer = "\n".join(footer_parts)
    # 交接卫生（计入报告预算，紧预算时可被裁掉）：声明未决线索为可选，
    # 压制外层以更高单 call 成本盲目接续补查——措辞放结果侧而非工具
    # schema 侧，延迟面体量线不涨
    footer += (
        "\n（结论均附证据，可直接引用作答；「未决/建议后续」是可选线索，"
        "事实足够时无需自动补查。）"
    )
    kept, trimmed, footer = _trim_to_budget(lines, header, footer, token_cap)
    body = "\n".join([header, *kept, footer])
    if trimmed:
        body += f"\n（因报告预算截断，仅显示前 {len(kept)} 条结论。）"
    return body


READ_GROUP_HISTORY_SPEC = LLMToolSpec(
    name="read_group_history",
    description=(
        "阅读当前群归档消息的连续上下文：按来源引用展开命中附近"
        "（around/before/after），或按时间区间从头浏览。"
        "引用来自 search_group_history 的结果。返回按时间升序的"
        "消息、媒体占位与前后续读游标。只读。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "anchor": {"type": "string", "description": "来源引用（hr1 开头）"},
            "direction": {
                "type": "string",
                "enum": ["around", "before", "after"],
                "description": "锚点展开方向，缺省 around",
            },
            "start": {"type": "string", "description": "区间阅读起点（含）"},
            "end": {"type": "string", "description": "区间阅读终点（不含）"},
            "cursor": {"type": "string", "description": "续读游标"},
        },
        "required": [],
    },
)


async def run_group_history_search(deps: HistoryToolDeps, arguments, context) -> str:
    if context.chat_type != "group":
        return _PRIVATE_CHAT_REPLY
    group_id = context.group_id
    if not deps.is_enabled(group_id):
        return _DISABLED_REPLY
    state: HistoryToolState | None = getattr(context, "history", None)
    if state is None:
        return _DISABLED_REPLY

    raw_terms = arguments.get("terms") or []
    cursor = str(arguments.get("cursor") or "").strip()

    if cursor and not raw_terms:
        outcome = await asyncio.to_thread(
            deps.query_service.search_continue,
            group_id, state.session, cursor_token=cursor,
        )
        return _render_search_outcome(deps, outcome, state)
    if cursor:
        return "续查只需传 cursor，不要同时传搜索条件。"

    terms = [str(t).strip() for t in raw_terms if str(t).strip()]
    if not terms:
        return "缺少搜索词项：terms 至少提供一个非空词。"

    now = datetime.now(tz=BEIJING_TZ)
    start = (
        parse_history_time(str(arguments.get("start") or ""))
        if arguments.get("start") else None
    )
    end = parse_history_time(str(arguments.get("end") or "")) if arguments.get("end") else None
    bad_start = arguments.get("start") and start is None
    bad_end = arguments.get("end") and end is None
    if bad_start or bad_end:
        return "时间格式无法解析：请用 YYYY-MM-DD 或 ISO 8601（北京时间）。"
    end_dt = end or now
    start_dt = start or (end_dt - timedelta(days=DEFAULT_WINDOW_DAYS))
    if end_dt <= start_dt:
        return "结束时间需要晚于开始时间。"
    if end_dt - start_dt > timedelta(days=MAX_RANGE_DAYS):
        start_dt = end_dt - timedelta(days=MAX_RANGE_DAYS)

    speaker_user_ids: list[str] | None = None
    speaker = str(arguments.get("speaker") or "").strip()
    if speaker:
        if speaker.isdigit():
            speaker_user_ids = [speaker]
        else:
            candidates = deps.resolve_speaker(group_id, speaker)
            if not candidates:
                return f"没有找到叫「{speaker}」的群成员，请换用 QQ 号。"
            if len(candidates) > 1:
                listed = "、".join(candidates[:5])
                return f"「{speaker}」匹配到多位成员（QQ：{listed}），请用 QQ 号明确指定。"
            speaker_user_ids = candidates

    outcome = await asyncio.to_thread(
        deps.query_service.search,
        group_id, state.session,
        terms=terms,
        start_ts=start_dt.timestamp(),
        end_ts=end_dt.timestamp(),
        speaker_user_ids=speaker_user_ids,
        max_hits=5,
    )
    return _render_search_outcome(deps, outcome, state)


def _render_search_outcome(deps: HistoryToolDeps, outcome, state: HistoryToolState) -> str:
    if outcome.status is QueryStatus.INVALID_REQUEST:
        detail = outcome.detail or ""
        if detail == "bad_cursor":
            return "游标无效或已过期，请重新发起搜索。"
        return "请求参数无效，请检查词项与时间范围。"
    if outcome.status is QueryStatus.UNAVAILABLE:
        return "群聊归档暂时不可用，请稍后再试。"

    allowance = state.allowance(SEARCH_RESULT_TOKEN_CAP, batch_pending=0)
    coverage_line = _format_coverage(outcome.coverage)

    if not outcome.hits:
        if outcome.status is QueryStatus.PARTIAL:
            return (
                f"已扫描 {outcome.scanned_rows} 行未见命中，窗口未扫尽，"
                "不能断言历史中不存在；可用 cursor 续查。\n" + coverage_line
            )
        return "查询窗口内没有匹配的消息。\n" + coverage_line

    lines = []
    for hit in outcome.hits:
        preview = hit.text[:PREVIEW_CHARS] + ("…" if len(hit.text) > PREVIEW_CHARS else "")
        ref = deps.query_service.encode_ref(hit.row_id)
        lines.append(
            f"[{_format_ts(hit.ts)}] {_speaker_line(hit.user_id, hit.sender_name)}："
            f"{preview}（ref {ref}）"
        )
    header = f"命中 {len(outcome.hits)} 条（新→旧）："
    footer_parts = [coverage_line]
    if outcome.has_more and outcome.cursor_token:
        footer_parts.append(f"仍有更早候选，续查 cursor：{outcome.cursor_token}")
    footer = "\n".join(footer_parts)
    kept, trimmed, footer = _trim_to_budget(lines, header, footer, allowance)
    if not kept:
        return _BUDGET_REPLY
    # R09+F02：渲染截断丢弃了查询层已交付的命中时也必须重签——即使
    # 查询层已证窗口耗尽（has_more=False），被裁掉的命中仍需可续达。
    # 重签从"最后实际交付的命中"起（kept 行按 hits 顺序新→旧为前缀）；
    # 未截断时原游标本就有效，不重签、不谎称可续查
    lost_hits = len(kept) < len(outcome.hits)
    if trimmed and kept and (outcome.has_more or lost_hits):
        last_delivered = outcome.hits[min(len(kept), len(outcome.hits)) - 1]
        reissued = deps.query_service.reissue_search_after(
            state.session, outcome.internal_state, last_delivered
        )
        if reissued:
            footer = coverage_line + f"\n仍有更早候选，续查 cursor：{reissued}"
    body = "\n".join([header, *kept, footer])
    if trimmed:
        body += f"\n（因结果预算截断，仅显示前 {len(kept)} 条命中。）"
    state.consume(estimate_tokens(body))
    return body


async def run_group_history_count(deps: HistoryToolDeps, arguments, context) -> str:
    if context.chat_type != "group":
        return _PRIVATE_CHAT_REPLY
    group_id = context.group_id
    if not deps.is_enabled(group_id):
        return _DISABLED_REPLY
    state: HistoryToolState | None = getattr(context, "history", None)
    if state is None:
        return _DISABLED_REPLY

    raw_terms = arguments.get("terms") or []
    terms = [str(t).strip() for t in raw_terms if str(t).strip()]
    if not terms:
        return "缺少搜索词项：terms 至少提供一个非空词。"
    # N02：词项会回显进结果与回执，超长词项是预算旁路，入口直接拒绝
    if any(len(t) > COUNT_TERM_MAX_CHARS for t in terms):
        return f"搜索词项过长（单个 ≤ {COUNT_TERM_MAX_CHARS} 字符），请精简后重试。"

    # 时间语义与 search 完全一致（缺省 7 天、最大跨度 180 天钳制）；
    # 钳制事实显式写进回执，长区间由模型分段计数，不静默截断
    now = datetime.now(tz=BEIJING_TZ)
    start = (
        parse_history_time(str(arguments.get("start") or ""))
        if arguments.get("start") else None
    )
    end = parse_history_time(str(arguments.get("end") or "")) if arguments.get("end") else None
    if (arguments.get("start") and start is None) or (
        arguments.get("end") and end is None
    ):
        return "时间格式无法解析：请用 YYYY-MM-DD 或 ISO 8601（北京时间）。"
    end_dt = end or now
    start_dt = start or (end_dt - timedelta(days=DEFAULT_WINDOW_DAYS))
    if end_dt <= start_dt:
        return "结束时间需要晚于开始时间。"
    clamped = False
    if end_dt - start_dt > timedelta(days=MAX_RANGE_DAYS):
        start_dt = end_dt - timedelta(days=MAX_RANGE_DAYS)
        clamped = True

    outcome = await asyncio.to_thread(
        deps.query_service.count,
        group_id,
        terms=terms,
        start_ts=start_dt.timestamp(),
        end_ts=end_dt.timestamp(),
    )
    return _render_count_outcome(deps, outcome, state, terms, start_dt, end_dt, clamped)


def _count_window_text(start_dt: datetime, end_dt: datetime) -> str:
    """回执/结果的时间区间文案：统一换算北京时间（N03——原时区小时
    直接标注「北京时间」会把 UTC 边界写成差 8 小时的证据区间），
    含秒输入保留秒，end 标注不含。"""

    def _fmt(moment: datetime) -> str:
        local = moment.astimezone(BEIJING_TZ)
        pattern = "%Y-%m-%d %H:%M:%S" if local.second else "%Y-%m-%d %H:%M"
        return f"{local:{pattern}}"

    return f"{_fmt(start_dt)} 至 {_fmt(end_dt)}（北京时间，end 不含）"


def _render_count_outcome(
    deps: HistoryToolDeps,
    outcome,
    state: HistoryToolState,
    terms: list[str],
    start_dt: datetime,
    end_dt: datetime,
    clamped: bool,
) -> str:
    if outcome.status is QueryStatus.INVALID_REQUEST:
        return "请求参数无效，请检查词项与时间范围。"
    if outcome.status is QueryStatus.UNAVAILABLE:
        return "群聊归档暂时不可用，请稍后再试。"
    if outcome.status is QueryStatus.PARTIAL:
        return (
            "无法在时限内完成计数（窗口过大或归档繁忙），本次未产生回执；"
            "请缩小时间窗后重试。\n" + _format_coverage(outcome.coverage)
        )

    # N01：计数只证明「已存档且未撤回的可读记录」中的缺席。窗口与
    # 归档数据无交集（空库 / 采集前 / 全部撤回之外的"无数据"）时，
    # 0 条反映的是数据缺失而非内容缺席——不签回执，不构成证无
    coverage = outcome.coverage
    coverage_line = _format_coverage(coverage)
    if coverage is not None and coverage.total_messages == 0:
        return "本群暂无归档记录，无法做任何计数核验。\n" + coverage_line
    if (
        coverage is not None
        and coverage.earliest_ts is not None
        and coverage.latest_ts is not None
        and (
            end_dt.timestamp() <= coverage.earliest_ts
            or start_dt.timestamp() >= coverage.latest_ts
        )
    ):
        return (
            "该窗口与归档覆盖范围没有交集（早于归档起点或晚于最新记录），"
            "窗口内没有可检索的数据，计数不构成「从未出现」的证据；"
            "请对准归档覆盖的时间段。\n" + coverage_line
        )

    # N02：查询前检查可用额度；词项长度已在入口设帽，回执为有界模板
    allowance = state.allowance(COUNT_RESULT_TOKEN_CAP, batch_pending=0)
    if allowance <= 0:
        return _BUDGET_REPLY

    terms_text = "、".join(f"「{t}」" for t in terms[:5])
    window_text = _count_window_text(start_dt, end_dt)
    clamp_note = (
        "窗口已按最大跨度收敛为最近 180 天；更早区间请分段计数。"
        if clamped else ""
    )
    # 回执登记面由宿主注入：调查子面是 RecordingQueryService（可作
    # evidence_refs），直接面不注册本工具，此处鸭子类型即可
    register = getattr(deps.query_service, "register_count_receipt", None)
    receipt_ref = register(
        terms_text, window_text, int(outcome.count or 0),
        coverage_note=_compact_coverage_note(coverage),
    ) if register is not None else None
    receipt_clause = f"（回执 {receipt_ref}）" if receipt_ref else ""

    header = f"计数核验{receipt_clause}："
    if outcome.count == 0:
        main = (
            f"窗口 {window_text} 内{terms_text}"
            "共 0 条命中（全量扫描已归档且未撤回的记录，非抽样）。"
            "0 条为确定性结论：这些词在该窗口的已归档可读记录中从未"
            "出现（以归档覆盖为准，停机缺漏不在其内，见下）。"
        )
    else:
        main = (
            f"窗口 {window_text} 内{terms_text}"
            f"共 {outcome.count} 条命中（全量扫描已归档且未撤回的记录）。"
            "计数只证明出现过，不是行级证据；定位具体消息请用 "
            "search_group_history。"
        )
    footer_parts = [coverage_line]
    if clamp_note:
        footer_parts.append(clamp_note)
    footer = "\n".join(footer_parts)
    kept, trimmed, footer = _trim_to_budget([main], header, footer, allowance)
    if not kept:
        return _BUDGET_REPLY
    body = "\n".join([header, *kept, footer])
    if trimmed:
        body += "\n（因结果预算截断，计数说明不完整。）"
    state.consume(estimate_tokens(body))
    return body


def _compact_coverage_note(coverage) -> str:
    """回执内嵌的紧凑覆盖说明（N01：证据自带范围限定）。"""
    if coverage is None:
        return "归档覆盖暂不可知"
    if coverage.total_messages == 0 or coverage.earliest_ts is None:
        return "本群暂无归档记录"
    earliest = datetime.fromtimestamp(coverage.earliest_ts, tz=BEIJING_TZ)
    latest = datetime.fromtimestamp(coverage.latest_ts, tz=BEIJING_TZ)
    return f"归档覆盖 {earliest:%Y-%m-%d} 至 {latest:%Y-%m-%d}，连续性未知"


async def run_group_history_read(deps: HistoryToolDeps, arguments, context) -> str:
    if context.chat_type != "group":
        return _PRIVATE_CHAT_REPLY
    group_id = context.group_id
    if not deps.is_enabled(group_id):
        return _DISABLED_REPLY
    state: HistoryToolState | None = getattr(context, "history", None)
    if state is None:
        return _DISABLED_REPLY

    cursor = str(arguments.get("cursor") or "").strip()
    anchor = str(arguments.get("anchor") or "").strip()
    direction = str(arguments.get("direction") or "around").strip()
    if direction not in ("around", "before", "after"):
        return "direction 仅支持 around/before/after。"

    if cursor:
        outcome = await asyncio.to_thread(
            deps.query_service.read_continue,
            group_id, state.session, cursor_token=cursor,
        )
        return _render_read_outcome(deps, outcome, state)
    if anchor:
        outcome = await asyncio.to_thread(
            deps.query_service.read_anchor,
            group_id, state.session,
            ref=anchor, direction=direction,
            radius=READ_RADIUS_DEFAULT,
            max_messages=READ_MAX_MESSAGES,
            max_chars=READ_RESULT_TOKEN_CAP * 2,
        )
        return _render_read_outcome(deps, outcome, state)

    start_raw = arguments.get("start")
    end_raw = arguments.get("end")
    if not start_raw:
        return "请提供 anchor、start/end 或 cursor 之一。"
    start = parse_history_time(str(start_raw))
    end = parse_history_time(str(end_raw)) if end_raw else datetime.now(tz=BEIJING_TZ)
    if start is None or (end_raw and end is None):
        return "时间格式无法解析：请用 YYYY-MM-DD 或 ISO 8601（北京时间）。"
    if end <= start:
        return "结束时间需要晚于开始时间。"
    outcome = await asyncio.to_thread(
        deps.query_service.read_range,
        group_id, state.session,
        start_ts=start.timestamp(), end_ts=end.timestamp(),
        max_messages=READ_MAX_MESSAGES,
        max_chars=READ_RESULT_TOKEN_CAP * 2,
    )
    return _render_read_outcome(deps, outcome, state)


def _render_read_outcome(deps: HistoryToolDeps, outcome, state: HistoryToolState) -> str:
    if outcome.status is QueryStatus.INVALID_REQUEST:
        if outcome.detail == "bad_cursor":
            return "游标无效或已过期，请重新发起阅读。"
        if outcome.detail == "bad_ref":
            return "来源引用无效（格式错误或归档已更换），请重新搜索获取。"
        if outcome.detail == "anchor_unavailable":
            return "该来源引用当前不可访问（不存在、已撤回或不属于本群）。"
        return "请求参数无效。"
    if outcome.status is QueryStatus.UNAVAILABLE:
        return "群聊归档暂时不可用，请稍后再试。"
    if outcome.status is QueryStatus.EMPTY or not outcome.messages:
        return "指定范围内没有可读的归档消息。\n" + _format_coverage(outcome.coverage)

    allowance = state.allowance(READ_RESULT_TOKEN_CAP, batch_pending=0)
    lines = []
    # F02：逐行记录 (消息, 前缀长度)——重签偏移按"渲染后实际交付的
    # 正文字符"计，而不是查询层消息对象的全长（否则跳过被裁掉的正文）
    line_meta: list[tuple[ArchivedMessage, int]] = []
    for message in outcome.messages:
        text = message.text
        if outcome.fragment is not None and message.row_id == outcome.fragment[0]:
            text += "…（长消息片段，续读可得剩余部分）"
        if message.image_count:
            text += f" [图片x{message.image_count}]"
        # R08：每条可引用消息携带来源引用（时间浏览也能拿到可提交的 ref）
        ref = deps.query_service.encode_ref(message.row_id)
        prefix = (
            f"[{_format_ts(message.ts)}] "
            f"{_speaker_line(message.user_id, message.sender_name)}："
        )
        lines.append(f"{prefix}{text}（ref {ref}）")
        line_meta.append((message, len(prefix)))
    header = "归档消息（时间升序）："
    # 游标行置于覆盖信息之前：footer 被裁时续读句柄优先存活
    footer_parts = []
    if outcome.older_cursor:
        footer_parts.append("older_cursor=" + outcome.older_cursor)
    if outcome.newer_cursor:
        footer_parts.append("newer_cursor=" + outcome.newer_cursor)
    footer_parts.append(_format_coverage(outcome.coverage))
    footer = "\n".join(footer_parts)
    kept, trimmed, footer = _trim_to_budget(lines, header, footer, allowance)
    if not kept:
        return _BUDGET_REPLY
    if trimmed and kept:
        # R09+F02：newer 续读从"最后实际交付的正文位置"重签。偏移来源
        # 是渲染层真实交付量（kept 行与原行比对，扣除 _clip_line 追加的
        # 省略号），不是查询层片段的全长
        index = min(len(kept), len(lines)) - 1
        last_message, prefix_len = line_meta[index]
        clipped = kept[-1] != lines[index]
        delivered_content = len(kept[-1]) - (1 if clipped else 0)
        delivered_text = min(
            len(last_message.text), max(0, delivered_content - prefix_len)
        )
        offset = 0
        if (
            outcome.fragment is not None
            and last_message.row_id == outcome.fragment[0]
        ):
            # 片段行：续读从片段起点 + 本次实际交付的正文
            offset = outcome.fragment[1] + delivered_text
        elif delivered_text < len(last_message.text):
            # 行被裁在正文内部：该消息剩余部分按片段续读，不整条跳过
            offset = delivered_text
        reissued = deps.query_service.reissue_read_newer_after(
            state.session, outcome.newer_state, last_message, char_offset=offset
        )
        if reissued:
            if outcome.newer_cursor:
                footer = footer.replace(
                    "newer_cursor=" + outcome.newer_cursor,
                    "newer_cursor=" + reissued,
                )
            else:
                # 查询层已耗尽未签令牌（F02）：渲染截断产生的新句柄前插
                footer = "newer_cursor=" + reissued + "\n" + footer
    body = "\n".join([header, *kept, footer])
    if trimmed:
        hint = "用 newer_cursor 续读" if "newer_cursor=" in footer else "以更早时间另开区间"
        body += f"\n（因结果预算截断，仅显示前 {len(kept)} 条；{hint}。）"
    state.consume(estimate_tokens(body))
    return body
