"""LLM 用量捕获：``_USAGE_SCOPE`` ContextVar 归因 + ``_record_usage`` 落库。

照搬 ``trace.py`` 的 ``collect_trace_calls`` contextmanager 范式（非装饰器，因
归因字段需调用时动态传）。``_record_usage`` 在 provider ``complete()`` 内经
``_schedule_usage_record`` fire-and-forget 调度，计量失败**绝不影响主聊天
路径**——全程 try/except 只 logger.exception。
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


_ENVELOPE_TOKENS: ContextVar[int | None] = ContextVar(
    "quickquip_llm_envelope_tokens", default=None,
)


@contextmanager
def envelope_meter(tokens: int | None) -> Iterator[None]:
    """设置当前回合【轮次上下文】信封的 token 估算值；退出复位（镜像 usage_scope 范式）。

    Agent Loop 内多次 complete() 落的每行都带同值——看板按 AVG 解读为每轮成本，
    禁止 SUM（同回合会在多行上重复计）。
    """
    token = _ENVELOPE_TOKENS.set(tokens)
    try:
        yield
    finally:
        _ENVELOPE_TOKENS.reset(token)


_EPOCH_HISTORY_TOKENS: ContextVar[int | None] = ContextVar(
    "quickquip_llm_epoch_history_tokens", default=None,
)


@contextmanager
def epoch_meter(tokens: int | None) -> Iterator[None]:
    """设置当前回合纪元 history（[anchor, head) 区间）的 token 估算值；退出复位。

    与 envelope_meter 同范式：Agent Loop 内每行同值，看板按 AVG 解读，禁止 SUM。
    """
    token = _EPOCH_HISTORY_TOKENS.set(tokens)
    try:
        yield
    finally:
        _EPOCH_HISTORY_TOKENS.reset(token)


_MEDIA_IMAGE_COUNT: ContextVar[int | None] = ContextVar(
    "quickquip_llm_media_image_count", default=None,
)


@contextmanager
def media_meter(count: int | None) -> Iterator[None]:
    """设置当前回合实际随请求附带的图片数；退出复位（镜像 epoch_meter 范式）。

    Agent Loop 内多次 complete() 落的每行都带同值——看板按 AVG 解读为每轮
    附带量，禁止 SUM。计数取自组装后的 LLMRequest（provider 序列化另有
    每请求 5 张上限）。
    """
    token = _MEDIA_IMAGE_COUNT.set(count)
    try:
        yield
    finally:
        _MEDIA_IMAGE_COUNT.reset(token)


_PATCH_TOKENS: ContextVar[int | None] = ContextVar(
    "quickquip_llm_patch_tokens", default=None,
)


@contextmanager
def patch_meter(tokens: int | None) -> Iterator[None]:
    """设置当前回合【现场】补丁的 token 估算值；退出复位（镜像 media_meter 范式）。

    与预算同单位（estimate_tokens 逐条求和），看板按 AVG 直接读作预算利用率，
    禁止 SUM。补丁在尾巴段每轮全价、不计入纪元 CTX 预算。
    """
    token = _PATCH_TOKENS.set(tokens)
    try:
        yield
    finally:
        _PATCH_TOKENS.reset(token)


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
        from quickquip.llm.provider.trace import current_agent_loop_id
        loop_id = current_agent_loop_id()  # 复用 trace.py 的 agent loop 边界，零接线
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
            # input_tokens 列存的是原始上报值：claude 协议按 exclusive 口径上报
            # （不含 cache_read/cache_creation），其余协议 inclusive。标签描述
            # 列值口径，与 canonical（恒 inclusive）是两回事（issue #202）
            input_token_semantics = (
                "exclusive" if client.config.protocol == "claude" else "inclusive"
            )
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
            "agent_loop_id": loop_id,
            "envelope_tokens": _ENVELOPE_TOKENS.get(),
            "epoch_history_tokens": _EPOCH_HISTORY_TOKENS.get(),
            "media_image_count": _MEDIA_IMAGE_COUNT.get(),
            "patch_tokens": _PATCH_TOKENS.get(),
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
        from quickquip.llm.usage_store import usage_store
        await asyncio.to_thread(usage_store.record, row)
    except (OSError, sqlite3.Error):
        logger.exception("LLM usage record failed")
    except Exception:
        logger.exception("LLM usage record unexpected error")


_USAGE_TASKS: set[asyncio.Task] = set()


def _schedule_usage_record(
    client,
    request,
    response,
    started: float,
    stream_used: bool,
    state: str,
    error_msg: str = "",
) -> None:
    """Fire-and-forget 调度计量任务，绝不把写库等待挂到聊天请求上。

    事件循环对 task 只持弱引用，必须自持强引用防止任务被 GC 中途回收。
    """
    task = asyncio.create_task(
        _record_usage(client, request, response, started, stream_used, state, error_msg)
    )
    _USAGE_TASKS.add(task)
    task.add_done_callback(_USAGE_TASKS.discard)


async def drain_usage_tasks(rounds: int = 3) -> None:
    """等待在途计量任务完成（进程关停排空；测试亦用于断言前排空）。

    有界多轮排空覆盖 drain 期间新入队的任务（关停瞬间仍在途的聊天请求
    会在其后才调度计量）；关停钩子不等待在途事件处理器，超出轮数的任务
    按 best-effort 放弃。
    """
    for _ in range(rounds):
        if not _USAGE_TASKS:
            break
        await asyncio.gather(*list(_USAGE_TASKS), return_exceptions=True)
