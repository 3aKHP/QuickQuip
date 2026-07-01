"""Provider 健康探活。

无状态、按需触发：``/llm probe`` 命令、reload 后验证、Web Admin 手动探活共用同一套实现。
不缓存、不定时——每次调用即每次计费，绝不静默扣费（项目 opt-in 原则）。
需要常驻监控时再引入定时器 + 缓存，那是另一个功能。
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any

from quickquip.llm.config import LLMConfig, ProviderConfig

PROBE_TIMEOUT_SECONDS = 5.0
_PROBE_MAX_TOKENS = 1
_PROBE_MODEL_FALLBACK = "gpt-4o-mini"


@dataclass(slots=True)
class ProviderHealth:
    """单次探活的结果。status ∈ {"ok", "error", "skipped"}。

    "skipped" 表示因 api_key 未设置等原因未发请求，不计费。
    """

    provider_id: str
    model: str
    status: str
    latency_ms: float | None = None
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "model": self.model,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


def _resolve_probe_model(provider: ProviderConfig, model: str | None) -> str:
    return model or provider.default_model or _PROBE_MODEL_FALLBACK


def _api_key_set(provider: ProviderConfig) -> bool:
    return bool(provider.api_key_env) and bool(os.getenv(provider.api_key_env, ""))


async def probe_provider(
    provider: ProviderConfig,
    *,
    model: str | None = None,
    timeout: float = PROBE_TIMEOUT_SECONDS,
) -> ProviderHealth:
    """探活单个 provider：发一条 max_tokens=1 的 "hi"。

    api_key 未设置的 provider 直接返回 "skipped"，不产生计费。
    传入 model 为 None 时用 provider.default_model。
    """
    from quickquip.llm.provider import LLMRequest, build_provider_client
    from quickquip.llm.tools import LLMConversationMessage

    probe_model = _resolve_probe_model(provider, model)

    if not _api_key_set(provider):
        return ProviderHealth(provider.id, probe_model, "skipped", error="api_key_missing")

    request = LLMRequest(
        model=probe_model,
        system_prompt="",
        messages=[LLMConversationMessage(role="user", content="hi")],
        temperature=0.0,
        max_output_tokens=_PROBE_MAX_TOKENS,
    )
    client = build_provider_client(provider)
    started = time.monotonic()
    try:
        await asyncio.wait_for(client.complete(request), timeout=timeout)
        latency_ms = round((time.monotonic() - started) * 1000, 1)
        return ProviderHealth(provider.id, probe_model, "ok", latency_ms=latency_ms)
    except asyncio.TimeoutError:
        latency_ms = round(timeout * 1000)
        return ProviderHealth(provider.id, probe_model, "error", latency_ms=latency_ms, error="timeout")
    except Exception as exc:
        latency_ms = round((time.monotonic() - started) * 1000, 1)
        return ProviderHealth(provider.id, probe_model, "error", latency_ms=latency_ms, error=type(exc).__name__)


async def probe_all_providers(
    config: LLMConfig,
    *,
    timeout: float = PROBE_TIMEOUT_SECONDS,
) -> list[ProviderHealth]:
    """并发探活所有 provider，总耗时 ≈ 单次 timeout，不随 provider 数线性增长。"""
    if not config.providers:
        return []
    return await asyncio.gather(
        *(probe_provider(p, timeout=timeout) for p in config.providers.values())
    )


def format_probe_results(results: list[ProviderHealth]) -> str:
    """格式化探活结果为聊天文本（/llm probe 与 reload 摘要共用）。"""
    if not results:
        return "没有已配置的 provider。"
    icon = {"ok": "✅", "error": "❌", "skipped": "⚪"}
    lines = [f"🔍 Provider 探活（{len(results)} 个，并发）"]
    for r in results:
        latency = f"{r.latency_ms}ms" if r.latency_ms is not None else "-"
        if r.status == "ok":
            lines.append(f"{icon['ok']} {r.provider_id} / {r.model}    {latency}  正常")
        elif r.status == "skipped":
            reason = "api_key 未设置" if r.error == "api_key_missing" else "跳过"
            lines.append(f"{icon['skipped']} {r.provider_id} / {r.model}    {reason}")
        else:
            label = "超时" if r.error == "timeout" else (r.error or "失败")
            lines.append(f"{icon['error']} {r.provider_id} / {r.model}    {label}（{latency}）")
    ok_count = sum(1 for r in results if r.status == "ok")
    lines.append(f"合计：{ok_count}/{len(results)} 正常")
    return "\n".join(lines)
