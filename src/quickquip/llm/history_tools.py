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

BEIJING_TZ = ZoneInfo("Asia/Shanghai")
"""工具时间语义与轮次信封一致（北京时间）；date-only 输入按此解释。"""

HISTORY_TOOLS = ("search_group_history", "read_group_history")

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


def _trim_to_budget(
    lines: list[str], header: str, footer: str, token_cap: int
) -> tuple[list[str], bool]:
    """从头保留行直到整包估算超帽；返回 (行列表, 是否截断)。"""
    if token_cap <= 0:
        return [], False
    kept: list[str] = []
    for index, line in enumerate(lines):
        candidate = "\n".join([header, *kept, line, footer])
        if estimate_tokens(candidate) > token_cap and kept:
            return kept, True
        kept.append(line)
    return kept, False


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
    kept, trimmed = _trim_to_budget(lines, header, footer, allowance)
    if not kept:
        return _BUDGET_REPLY
    body = "\n".join([header, *kept, footer])
    if trimmed:
        body += f"\n（因结果预算截断，仅显示前 {len(kept)} 条；可续查。）"
    state.consume(estimate_tokens(body))
    return body


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
    for message in outcome.messages:
        text = message.text
        if outcome.fragment is not None and message.row_id == outcome.fragment[0]:
            text += "…（长消息片段，续读可得剩余部分）"
        if message.image_count:
            text += f" [图片x{message.image_count}]"
        lines.append(
            f"[{_format_ts(message.ts)}] "
            f"{_speaker_line(message.user_id, message.sender_name)}：{text}"
        )
    header = "归档消息（时间升序）："
    footer_parts = [_format_coverage(outcome.coverage)]
    if outcome.older_cursor:
        footer_parts.append("older_cursor=" + outcome.older_cursor)
    if outcome.newer_cursor:
        footer_parts.append("newer_cursor=" + outcome.newer_cursor)
    footer = "\n".join(footer_parts)
    kept, trimmed = _trim_to_budget(lines, header, footer, allowance)
    if not kept:
        return _BUDGET_REPLY
    body = "\n".join([header, *kept, footer])
    if trimmed:
        body += f"\n（因结果预算截断，仅显示前 {len(kept)} 条；可续读。）"
    state.consume(estimate_tokens(body))
    return body
