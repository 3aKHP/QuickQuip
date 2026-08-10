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

from quickquip.llm.pricing import estimate_cost, match_pricing, normalize_usage

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
        if response is not None and state == "ok":
            usage = normalize_usage(
                client.config.protocol,
                response.input_tokens,
                response.output_tokens,
                response.cache_creation_tokens,
                response.cache_read_tokens,
            )
            rates = match_pricing(model, _configured_pricing())
            cost_usd, priced_flag = estimate_cost(usage, rates)
            priced = 1 if priced_flag else 0

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
            "output_tokens": response.output_tokens if response else None,
            "cache_creation_tokens": response.cache_creation_tokens if response else None,
            "cache_read_tokens": response.cache_read_tokens if response else None,
            "thinking_tokens": response.thinking_tokens if response else None,
            "cost_usd": cost_usd,
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
