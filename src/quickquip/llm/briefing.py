from __future__ import annotations

import logging
from dataclasses import replace

from quickquip.chat.daily_briefing import DailyBriefingContext
from quickquip.llm.config import DailyBriefingConfig, LLMConfig, PersonaConfig
from quickquip.llm.provider import LLMProviderError, LLMRequest, build_provider_client
from quickquip.llm.provider import strip_leading_reasoning_content
from quickquip.llm.tools import LLMConversationMessage
from quickquip.llm.usage import set_usage_scope

logger = logging.getLogger(__name__)

_BRIEFING_MAX_OUTPUT_TOKENS = 8192
_BRIEFING_TEMPERATURE = 0.8
_NORMAL_FINISH_REASONS: frozenset[str] = frozenset({"stop", "end_turn", "stop_sequence", "STOP"})
_PERIOD_INSTRUCTIONS = {
    "morning": "你现在要写一条群聊早报。重点是开场、回顾昨天的群聊氛围，并自然带出今天的开始。",
    "noon": "你现在要写一条群聊午报。重点是中场播报，概括今天到中午为止的节奏，语气轻快一些。",
    "evening": "你现在要写一条群聊晚报。重点是收尾、复盘今天的群聊动静，并带一点休息前的氛围。",
}


def _build_system_prompt(
    persona: PersonaConfig,
    context: DailyBriefingContext,
    briefing_config: DailyBriefingConfig,
) -> str:
    parts: list[str] = []
    if persona.system_prompt:
        parts.append(persona.system_prompt)
    if persona.style_prompt:
        parts.append(persona.style_prompt)

    parts.append(
        _PERIOD_INSTRUCTIONS[context.period]
        + f" 输出必须是一条适合直接发到 QQ 群里的 {context.period_label}。"
        f" 成文长度控制在 {briefing_config.max_output_chars} 字以内。"
        " 不要写成公文，不要写标题党，也不要堆很多列表。"
        " 可以分 2 到 4 小段，但整体要紧凑。"
        " 如果数据不多，也要保持自然，不要生硬地凑字数。"
        " 你可以点到活跃用户和热词，但不要做僵硬点名或排行榜播音腔。"
        " 若提供了新闻占位信息，只能顺手一提，不要喧宾夺主。"
    )
    return "\n\n".join(parts)


def _format_sample_messages(sample_messages: list[dict]) -> str:
    if not sample_messages:
        return "（本窗口暂无消息样本）"

    lines: list[str] = []
    for entry in sample_messages:
        sender = str(entry.get("sender", "")).strip() or "未知"
        text = str(entry.get("text", "")).strip()
        if not text:
            continue
        ts = str(entry.get("time_label", "")).strip()
        prefix = f"[{ts}] " if ts else ""
        lines.append(f"{prefix}{sender}：{text}")
    return "\n".join(lines) if lines else "（本窗口暂无消息样本）"


def _build_user_prompt(context: DailyBriefingContext) -> str:
    lines = [
        f"播报类型：{context.period_label}",
        f"当前日期：{context.date_label} 星期{context.weekday_label}",
        f"当前时间：{context.current_time_label}",
        f"统计窗口：{context.window_label}",
        f"窗口消息总数：{context.message_count}",
    ]

    if context.active_users:
        lines.append("活跃用户：")
        for item in context.active_users:
            lines.append(f"- {item.display_name}：{item.message_count} 条")
    else:
        lines.append("活跃用户：暂无明显活跃用户")

    if context.hot_words:
        lines.append(f"热词：{' / '.join(context.hot_words)}")
    else:
        lines.append("热词：暂无明显热词")

    if context.news_items:
        lines.append("预留新闻位：")
        for item in context.news_items:
            suffix = f"（{item.source}）" if item.source else ""
            lines.append(f"- {item.title}{suffix}")

    lines.append("消息样本：")
    lines.append("=== 样本开始 ===")
    lines.append(_format_sample_messages(context.sample_messages))
    lines.append("=== 样本结束 ===")
    lines.append("")
    lines.append("请直接输出最终播报正文，不要附加解释。")
    return "\n".join(lines)


def _trim_output(text: str, max_chars: int) -> str:
    cleaned = strip_leading_reasoning_content(text).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    clipped = cleaned[:max_chars].rstrip()
    pos = max(clipped.rfind("\n"), clipped.rfind("。"), clipped.rfind("！"), clipped.rfind("？"))
    if pos >= max_chars // 2:
        clipped = clipped[:pos + 1].rstrip()
    return clipped.rstrip("，、；,;") + "……"


async def generate_daily_briefing(
    *,
    context: DailyBriefingContext,
    persona: PersonaConfig,
    group_id: int | str,
    briefing_config: DailyBriefingConfig,
    llm_config: LLMConfig,
    default_provider_id: str,
    default_model: str,
) -> tuple[str, str]:
    set_usage_scope("briefing", group_id=str(group_id))
    system_prompt = _build_system_prompt(persona, context, briefing_config)
    user_message = LLMConversationMessage(role="user", content=_build_user_prompt(context))
    cascade = briefing_config.model_cascade or [f"{default_provider_id}/{default_model}"]
    last_error: Exception | None = None

    for entry in cascade:
        if entry == "@default":
            provider_id = default_provider_id
            model = default_model
        else:
            parts = entry.split("/", 1)
            if len(parts) != 2:
                logger.warning("daily_briefing: invalid cascade entry %r, skipping", entry)
                continue
            provider_id, model = parts

        provider_config = llm_config.providers.get(provider_id)
        if provider_config is None:
            logger.warning("daily_briefing: provider %r not found in config, skipping", provider_id)
            continue

        effective_config = replace(provider_config, stream_enabled=False)
        req = LLMRequest(
            model=model,
            system_prompt=system_prompt,
            messages=[user_message],
            temperature=_BRIEFING_TEMPERATURE,
            max_output_tokens=_BRIEFING_MAX_OUTPUT_TOKENS,
            tools=[],
            allow_tool_calls=False,
            tool_choice="none",
        )

        try:
            client = build_provider_client(effective_config)
            response = await client.complete(req)
            text = _trim_output(response.text, briefing_config.max_output_chars)
            finish = (response.finish_reason or "").strip()
            if text and (not finish or finish in _NORMAL_FINISH_REASONS):
                logger.info(
                    "daily_briefing: generated for group %s via %s/%s (%d chars, finish=%s)",
                    group_id,
                    provider_id,
                    model,
                    len(text),
                    finish or "n/a",
                )
                return text, f"{provider_id}/{model}"
            if text:
                logger.warning(
                    "daily_briefing: %s/%s non-normal finish_reason=%r (%d chars), trying next",
                    provider_id,
                    model,
                    response.finish_reason,
                    len(text),
                )
                last_error = RuntimeError(f"non-normal finish_reason: {response.finish_reason!r}")
                continue
            logger.warning("daily_briefing: %s/%s returned empty text, trying next", provider_id, model)
        except LLMProviderError as exc:
            logger.warning(
                "daily_briefing: %s/%s provider error: %s, trying next",
                provider_id,
                model,
                exc,
            )
            last_error = exc
        except Exception as exc:
            logger.warning(
                "daily_briefing: %s/%s unexpected error: %s, trying next",
                provider_id,
                model,
                exc,
            )
            last_error = exc

    raise RuntimeError(f"所有模型均调用失败，最后错误：{last_error}")
