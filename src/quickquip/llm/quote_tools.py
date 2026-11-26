"""LLM 当前群语录只读查询工具核心（#343）。"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import json
import sqlite3
from typing import Any
from zoneinfo import ZoneInfo

from quickquip.chat.group_quotes import resolve_quote_display_name
from quickquip.common.identity_sources import IdentitySnapshot
from quickquip.llm.token_estimate import estimate_tokens
from quickquip.llm.tools import LLMToolOutput, LLMToolSpec, ToolExecutionContext

BEIJING_TZ = ZoneInfo("Asia/Shanghai")

QUERY_GROUP_QUOTES_TOOL_NAME = "query_group_quotes"
QUOTE_DEFAULT_LIMIT = 10
QUOTE_MAX_LIMIT = 20
QUOTE_KEYWORD_MAX_CHARS = 100
QUOTE_SPEAKER_MAX_CHARS = 64
QUOTE_CONTENT_MAX_CHARS = 300
QUOTE_RESULT_TOKEN_CAP = 1200
QUOTE_LOOP_BUDGET_TOKENS = 3600

QUERY_GROUP_QUOTES_SPEC = LLMToolSpec(
    name=QUERY_GROUP_QUOTES_TOOL_NAME,
    description=(
        "只读查询当前群已收藏的语录。支持按编号 seq 精确查看，或按关键词 keyword / "
        "发言人 speaker 搜索，不传参数时按最新收藏倒序浏览。仅群聊可用，不自动写入记忆。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "seq": {
                "type": "integer",
                "description": "本群语录编号（#N 中的 N，>=1），传入时精确查看单条",
            },
            "keyword": {
                "type": "string",
                "description": "按语录正文或被提及成员搜索的关键词",
            },
            "speaker": {
                "type": "string",
                "description": "按发言人筛选（支持 QQ 号、群名片或身份别名）",
            },
            "limit": {
                "type": "integer",
                "description": f"每页条数（1-{QUOTE_MAX_LIMIT}，默认 {QUOTE_DEFAULT_LIMIT}）",
            },
            "offset": {
                "type": "integer",
                "description": "分页偏移量（>=0，默认 0）",
            },
        },
        "required": [],
    },
)


@dataclass(slots=True)
class QuoteToolDeps:
    quote_store: Any
    resolve_speaker: Callable[[int | str, str], list[str]]
    get_identity_snapshot: Callable[[int | str], IdentitySnapshot]


def redact_quote_arguments(arguments_json: str) -> str:
    """仅保留结构化模式字段，不落库 keyword / speaker 原文（ADR-0005）。"""
    try:
        parsed = json.loads(arguments_json) if arguments_json else {}
    except (TypeError, ValueError):
        return "{}"
    if not isinstance(parsed, dict):
        return "{}"
    if parsed.get("seq") is not None:
        return json.dumps({"mode": "seq", "has_seq": True}, ensure_ascii=False, sort_keys=True)
    has_keyword = bool(str(parsed.get("keyword") or "").strip())
    has_speaker = bool(str(parsed.get("speaker") or "").strip())
    mode = "filter" if (has_keyword or has_speaker) else "list"
    payload: dict[str, object] = {
        "mode": mode,
        "has_keyword": has_keyword,
        "has_speaker": has_speaker,
    }
    if isinstance(parsed.get("offset"), int) and not isinstance(parsed.get("offset"), bool):
        payload["offset"] = max(0, parsed["offset"])
    if isinstance(parsed.get("limit"), int) and not isinstance(parsed.get("limit"), bool):
        payload["limit"] = max(1, min(parsed["limit"], QUOTE_MAX_LIMIT))
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _format_saved_at(raw: object) -> str:
    if raw is None:
        return "时间未知"
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return datetime.fromtimestamp(float(raw), tz=BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
    text = str(raw).strip()
    if not text:
        return "时间未知"
    try:
        return datetime.fromtimestamp(float(text), tz=BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        pass
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is not None:
            dt = dt.astimezone(BEIJING_TZ)
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text[:16]


def _format_quote_line(row: dict[str, Any], snapshot: IdentitySnapshot) -> str:
    seq = row.get("group_seq")
    uid = str(row.get("quoted_user_id") or "").strip()
    snapshot_name = str(row.get("quoted_sender_name") or "").strip()
    resolved_name, changed = resolve_quote_display_name(
        uid, snapshot_name, identity_snapshot=snapshot
    )
    speaker_label = resolved_name or "未知"
    meta_parts: list[str] = []
    if uid:
        meta_parts.append(f"QQ {uid}")
    if changed and snapshot_name:
        meta_parts.append(f"原名：{snapshot_name}")
    if meta_parts:
        speaker_label = f"{speaker_label}（{'，'.join(meta_parts)}）"

    raw_content = str(row.get("content_display") or row.get("content") or "")
    content = " ".join(raw_content.split())
    if len(content) > QUOTE_CONTENT_MAX_CHARS:
        content = content[:QUOTE_CONTENT_MAX_CHARS] + "…"
    saved = _format_saved_at(row.get("saved_at"))
    return f"#{seq} [{saved}] {speaker_label}：{content}"


def _parse_int_arg(value: object, *, name: str) -> tuple[int | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, bool) or not isinstance(value, int):
        return None, f"参数 {name} 必须是整数。"
    return value, None


async def run_group_quote_query(
    arguments: dict[str, object],
    context: ToolExecutionContext,
    deps: QuoteToolDeps | None,
) -> LLMToolOutput:
    if context.chat_type != "group":
        return LLMToolOutput(content="该工具仅支持群聊使用。")
    if deps is None or deps.quote_store is None:
        return LLMToolOutput(content="当前运行时未接入群语录存储。", is_error=True)

    allowance = min(
        QUOTE_RESULT_TOKEN_CAP,
        max(0, QUOTE_LOOP_BUDGET_TOKENS - context.quote_query_tokens_used),
    )
    if allowance <= 0:
        return LLMToolOutput(content="本轮群语录查询额度已用完，请基于已获取的内容作答。")

    seq, seq_err = _parse_int_arg(arguments.get("seq"), name="seq")
    if seq_err:
        return LLMToolOutput(content=seq_err)
    limit_val, limit_err = _parse_int_arg(arguments.get("limit"), name="limit")
    if limit_err:
        return LLMToolOutput(content=limit_err)
    offset_val, offset_err = _parse_int_arg(arguments.get("offset"), name="offset")
    if offset_err:
        return LLMToolOutput(content=offset_err)

    keyword = str(arguments.get("keyword") or "").strip()
    speaker = str(arguments.get("speaker") or "").strip()
    if len(keyword) > QUOTE_KEYWORD_MAX_CHARS:
        return LLMToolOutput(
            content=f"搜索关键词过长（上限 {QUOTE_KEYWORD_MAX_CHARS} 字符），请精简后重试。"
        )
    if len(speaker) > QUOTE_SPEAKER_MAX_CHARS:
        return LLMToolOutput(
            content=f"发言人筛选条件过长（上限 {QUOTE_SPEAKER_MAX_CHARS} 字符），请精简后重试。"
        )

    group_id = str(context.group_id)
    snapshot = deps.get_identity_snapshot(group_id)

    if seq is not None:
        if seq <= 0:
            return LLMToolOutput(content="语录编号 seq 需要为正整数。")
        try:
            row, total_count = await asyncio.to_thread(
                deps.quote_store.get_by_seq_with_count,
                group_id,
                seq,
                identity_snapshot=snapshot,
            )
        except (RuntimeError, sqlite3.Error):
            return LLMToolOutput(content="群语录数据库暂时不可用，请稍后再试。", is_error=True)
        if row is None:
            return LLMToolOutput(
                content=f"当前群不存在编号为 #{seq} 的语录（本群共 {total_count} 条语录）。"
            )
        body = f"当前群语录 #{seq}：\n{_format_quote_line(row, snapshot)}"
        context.quote_query_tokens_used += estimate_tokens(body)
        return LLMToolOutput(content=body)

    raw_limit = limit_val if limit_val is not None else QUOTE_DEFAULT_LIMIT
    limit = max(1, min(raw_limit, QUOTE_MAX_LIMIT))
    offset = max(0, offset_val if offset_val is not None else 0)

    user_ids: list[str] = []
    name_pattern = ""
    if speaker:
        if speaker.isascii() and speaker.isdigit():
            user_ids = [speaker]
        else:
            candidates = deps.resolve_speaker(group_id, speaker)
            if len(candidates) > 1 and snapshot.ambiguous(set(candidates)):
                labels = [
                    f"{snapshot.name(uid) or uid}（QQ {uid}）"
                    for uid in candidates[:6]
                ]
                return LLMToolOutput(
                    content=(
                        f"发言人「{speaker}」匹配到多位群成员："
                        f"{'、'.join(labels)}。请改用具体 QQ 号或更精确的名字重查。"
                    )
                )
            user_ids = list(candidates)
            name_pattern = speaker

    try:
        rows, total = await asyncio.to_thread(
            deps.quote_store.search_filtered,
            group_id,
            keyword=keyword,
            user_ids=user_ids,
            name_pattern=name_pattern,
            offset=offset,
            limit=limit,
            identity_snapshot=snapshot,
        )
    except (RuntimeError, sqlite3.Error):
        return LLMToolOutput(content="群语录数据库暂时不可用，请稍后再试。", is_error=True)

    if total == 0:
        if keyword or speaker:
            return LLMToolOutput(content="当前群语录中没有匹配条件的记录。")
        return LLMToolOutput(content="当前群暂无已收藏的语录。")
    if not rows:
        return LLMToolOutput(content=f"已超出结果范围（共命中 {total} 条），没有更多语录。")

    kept_lines: list[str] = []
    used_tokens = 0
    truncated = False
    for row in rows:
        line = _format_quote_line(row, snapshot)
        line_tokens = estimate_tokens(line)
        if kept_lines and used_tokens + line_tokens > allowance:
            truncated = True
            break
        kept_lines.append(line)
        used_tokens += line_tokens

    start_idx = offset + 1
    end_idx = offset + len(kept_lines)
    header = f"当前群语录（共 {total} 条，本页显示 {start_idx}–{end_idx}）："
    parts = [header, *kept_lines]
    if end_idx < total:
        suffix = f"还有更早语录，可传 offset={end_idx} 续查。"
        if truncated:
            suffix = f"（本页因长度预算截断）{suffix}"
        parts.append(suffix)
    body = "\n".join(parts)
    context.quote_query_tokens_used += estimate_tokens(body)
    return LLMToolOutput(content=body)
