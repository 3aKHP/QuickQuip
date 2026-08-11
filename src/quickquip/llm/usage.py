"""LLM 用量捕获：``_USAGE_SCOPE`` ContextVar 归因 + ``_record_usage`` 落库。

照搬 ``trace.py`` 的 ``collect_trace_calls`` contextmanager 范式（非装饰器，因
归因字段需调用时动态传）。``_record_usage`` 在 provider ``complete()`` 内调用，
计量失败**绝不影响主聊天路径**——全程 try/except 只 logger.exception。
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

from quickquip.llm.pricing import estimate_cost_components, match_pricing, normalize_usage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class UsageScope:
    feature: str
    group_id: str | None = None
    persona_id: str | None = None


_USAGE_SCOPE: ContextVar[UsageScope | None] = ContextVar(
    "quickquip_llm_usage_scope", default=None,
)


@contextmanager
def usage_scope(
    feature: str,
    *,
    group_id: str | None = None,
    persona_id: str | None = None,
) -> Iterator[None]:
    """设置当前协程的用量归因；退出时复位（照搬 collect_trace_calls 范式）。"""
    token = _USAGE_SCOPE.set(UsageScope(feature, group_id, persona_id))
    try:
        yield
    finally:
        _USAGE_SCOPE.reset(token)


def set_usage_scope(
    feature: str,
    *,
    group_id: str | None = None,
    persona_id: str | None = None,
) -> None:
    """直接设置 scope（不 reset）。用于：(1) ``asyncio.create_task`` 隔离的子任务
    （跑在父 context 副本上，task 结束自动清理）；(2) 顶层 cron/handler 入口（调用方
    不再调 provider，残留无害）。调用链中间环节应优先用 ``usage_scope``（自动 reset）。"""
    _USAGE_SCOPE.set(UsageScope(feature, group_id, persona_id))


def _configured_pricing() -> dict:
    """从 llm_service 取 [pricing.models]（延迟 import 避免 provider↔service 循环）。"""
    try:
        from quickquip.llm.service import get_llm_service
        return get_llm_service().config.pricing
    except Exception:
        return {}


async def _record_usage(
    client,
    request,
    response,
    started: float,
    stream_used: bool,
    state: str,
    error_msg: str = "",
) -> None:
    """落一行用量（成功/错误/取消皆记）；任何异常只 logger 不抛。"""
    try:
        scope = _USAGE_SCOPE.get()
        try:
            from quickquip.llm.provider.trace import _AGENT_LOOP_TRACE
            loop = _AGENT_LOOP_TRACE.get()  # 复用 trace.py 的 agent loop 边界，零接线
        except Exception:
            loop = None
        model = response.model if response is not None else request.model
        duration_ms = (time.monotonic() - started) * 1000

        cost_usd = 0.0
        priced = 0
        input_cost_usd = 0.0
        output_cost_usd = 0.0
        cache_read_cost_usd = 0.0
        cache_creation_cost_usd = 0.0
        fresh_input_tokens = None
        total_tokens = None
        input_token_semantics = None
        pricing_model = None
        pricing_source = None
        pricing_confidence = None
        if response is not None and state == "ok":
            usage = normalize_usage(
                client.config.protocol,
                response.input_tokens,
                response.output_tokens,
                response.cache_creation_tokens,
                response.cache_read_tokens,
            )
            configured = _configured_pricing()
            rates = match_pricing(client.config.id, model, configured)
            components, priced_flag = estimate_cost_components(usage, rates)
            input_cost_usd = components["input_cost_usd"]
            output_cost_usd = components["output_cost_usd"]
            cache_read_cost_usd = components["cache_read_cost_usd"]
            cache_creation_cost_usd = components["cache_creation_cost_usd"]
            cost_usd = sum(components.values())
            priced = 1 if priced_flag else 0
            fresh_input_tokens = usage.fresh_input
            total_tokens = usage.total_tokens
            input_token_semantics = usage.input_token_semantics
            if rates is not None:
                pricing_model = f"{client.config.id}/{model}" if f"{client.config.id}/{model}" in configured else model
                pricing_source = rates.source
                pricing_confidence = rates.confidence

        row = {
            "provider_id": client.config.id,
            "protocol": client.config.protocol,
            "model": model,
            "feature": scope.feature if scope else None,
            "group_id": scope.group_id if scope else None,
            "persona_id": scope.persona_id if scope else None,
            "agent_loop_id": loop.loop_id if loop else None,
            "stream": 1 if stream_used else 0,
            "duration_ms": duration_ms,
            "input_tokens": response.input_tokens if response else None,
            "fresh_input_tokens": fresh_input_tokens,
            "total_tokens": total_tokens,
            "input_token_semantics": input_token_semantics,
            "output_tokens": response.output_tokens if response else None,
            "cache_creation_tokens": response.cache_creation_tokens if response else None,
            "cache_read_tokens": response.cache_read_tokens if response else None,
            "thinking_tokens": response.thinking_tokens if response else None,
            "cost_usd": cost_usd,
            "input_cost_usd": input_cost_usd,
            "output_cost_usd": output_cost_usd,
            "cache_read_cost_usd": cache_read_cost_usd,
            "cache_creation_cost_usd": cache_creation_cost_usd,
            "pricing_model": pricing_model,
            "pricing_source": pricing_source,
            "pricing_confidence": pricing_confidence,
            "priced": priced,
            "state": state,
            "error_message": error_msg or None,
        }
        from quickquip.app.message_pipeline import usage_store
        await asyncio.to_thread(usage_store.record, row)
    except (OSError, sqlite3.Error):
        logger.exception("LLM usage record failed")
    except Exception:
        logger.exception("LLM usage record unexpected error")
