"""quick_judge 诊断通道 — 极速判定的独立模块（v1.12.1 P5 自 ``service.py`` 抽出）。

``QuickJudgeResult``、provider 选择策略与 detailed 通道集中于此；
``LLMService`` 仅保留薄委托（``quick_judge`` / ``quick_judge_detailed``）。
通道不走群配置、不注入记忆、不启用工具，只发单条 system+user，
优先使用 ``[triggers.quick_judge]`` 配置的 provider/model。

窄接口契约：函数接收显式参数（``LLMConfig`` 与 ``client_builder``），
不接收 ``LLMService`` 实例。``client_builder`` 默认指向
``provider.build_provider_client``；``LLMService`` 委托时显式传入自身
模块级的 ``build_provider_client``，保持既有 patch 点
（``quickquip.llm.service.build_provider_client``）有效。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from time import monotonic

from quickquip.llm.config import LLMConfig, ProviderConfig
from quickquip.llm.provider import (
    BaseProviderClient,
    LLMRequest,
    build_provider_client,
    strip_leading_reasoning_content,
)
from quickquip.llm.tools import LLMConversationMessage

ClientBuilder = Callable[[ProviderConfig], BaseProviderClient]


@dataclass(slots=True)
class QuickJudgeResult:
    """quick-judge 的结构化结果（内部诊断通道）。

    ``outcome``: ok | empty | length | provider_error | no_provider；
    ``is_technical``（非 ok）是唯一的技术失败判定入口，调用方不得
    自行枚举 outcome 字符串。``to_diagnostic()`` 只输出允许记录的字段；
    ``error`` 仅供调用方重新抛出（quick_judge 公共契约），不得进入日志或诊断记录。
    """

    text: str
    outcome: str
    provider_id: str
    model: str
    finish_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    thinking_tokens: int | None = None
    duration_ms: float = 0.0
    error: Exception | None = None

    @property
    def is_technical(self) -> bool:
        return self.outcome != "ok"

    def to_diagnostic(self) -> dict:
        return {
            "outcome": self.outcome,
            "provider": self.provider_id,
            "model": self.model,
            "finish_reason": self.finish_reason,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "thinking_tokens": self.thinking_tokens,
            "duration_ms": round(self.duration_ms, 2),
        }


async def run_quick_judge_detailed(
    config: LLMConfig,
    prompt: str,
    max_tokens: int = 64,
    *,
    client_builder: ClientBuilder = build_provider_client,
) -> QuickJudgeResult:
    """``run_quick_judge`` 的结构化内部通道：按结果类别返回诊断字段，
    不抛 provider 异常。诊断只含 provider/model/类别/finish reason/
    token/耗时，禁止携带 prompt、模型原始响应、凭据或 endpoint。"""
    qj = config.quick_judge
    provider_id = qj.provider_id if qj.provider_id else config.runtime.default_provider
    if not provider_id or provider_id not in config.providers:
        provider_id = next(iter(config.providers), None)
    if not provider_id:
        return QuickJudgeResult(
            text='{"trigger": false}',
            outcome="no_provider",
            provider_id="",
            model="",
        )

    provider = config.providers[provider_id]
    judge_provider = replace(provider, stream_enabled=False)

    model = qj.model if qj.model else judge_provider.default_model

    request = LLMRequest(
        model=model,
        system_prompt="你是一个仅输出 JSON 的判定器。",
        messages=[
            LLMConversationMessage(role="user", content=prompt),
        ],
        temperature=0.0,
        max_output_tokens=max_tokens,
        thinking_budget=None,
        tools=[],
        allow_tool_calls=False,
        tool_choice="none",
    )
    client = client_builder(judge_provider)
    started = monotonic()
    try:
        response = await client.complete(request)
    except Exception as exc:
        return QuickJudgeResult(
            text="",
            outcome="provider_error",
            provider_id=provider_id,
            model=model,
            duration_ms=(monotonic() - started) * 1000,
            error=exc,
        )
    text = strip_leading_reasoning_content(response.text or "")
    finish_reason = (response.finish_reason or "").strip()
    outcome = "ok"
    if finish_reason.lower() in {"length", "max_tokens"}:
        # 截断优先于空正文判定：reasoning 耗尽预算时可见正文为空但根因是 length
        outcome = "length"
    elif not text:
        outcome = "empty"
    return QuickJudgeResult(
        text=text,
        outcome=outcome,
        provider_id=provider_id,
        model=model,
        finish_reason=finish_reason or None,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        thinking_tokens=response.thinking_tokens,
        duration_ms=(monotonic() - started) * 1000,
    )


async def run_quick_judge(
    config: LLMConfig,
    prompt: str,
    max_tokens: int = 64,
    *,
    client_builder: ClientBuilder = build_provider_client,
) -> str:
    """
    用于 context_rules 和 awakening 的极速判定调用。
    不走群配置、不注入记忆、不启用工具，只发单条 system+user。
    优先使用 [triggers.quick_judge] 配置的 provider/model。
    """
    result = await run_quick_judge_detailed(config, prompt, max_tokens, client_builder=client_builder)
    if result.outcome == "provider_error" and result.error is not None:
        # 保持既有公共契约：provider 异常继续上抛（调用方 fail-closed 自行处理）
        raise result.error
    return result.text
