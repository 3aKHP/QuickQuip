"""唤醒 LLM 判定域：quick-judge 通道调用、结果解析与判定缓存策略。"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from time import monotonic
from typing import Protocol, TYPE_CHECKING

from quickquip.common.json_utils import extract_json_object
from quickquip.llm.usage import usage_scope

from quickquip.chat.awakening.state import AwakeningState

if TYPE_CHECKING:
    from quickquip.llm.quick_judge import QuickJudgeResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Narrow judge-channel interfaces (structural typing: LLMService satisfies as-is)
# ---------------------------------------------------------------------------


class QuickJudgeSettingsView(Protocol):
    provider_id: str
    model: str
    timeout: float
    max_tokens: int


class RuntimeDefaultProviderView(Protocol):
    default_provider: str


class JudgeTargetSource(Protocol):
    """判定目标的窄读取面（``LLMService.config`` 即满足）。"""

    quick_judge: QuickJudgeSettingsView
    runtime: RuntimeDefaultProviderView


class QuickJudgeCaller(Protocol):
    async def quick_judge_detailed(
        self, prompt: str, max_tokens: int | None = None
    ) -> "QuickJudgeResult": ...


class AwakeningJudgeChannel(QuickJudgeCaller, Protocol):
    """触发判定链对 LLM 服务对象的全部依赖。"""

    @property
    def config(self) -> JudgeTargetSource: ...


RELEVANCE_SYSTEM = (
    "你是一个仅输出 JSON 的判定器。"
    "判断用户消息是否在延续或回应 bot 之前的对话。"
    '仅输出 {"score": 0.0} 到 {"score": 1.0}，score 越高越相关。'
)

QA_SYSTEM = (
    "你是一个仅输出 JSON 的判定器。"
    "判断用户消息是否是一个需要专业性回答的问题（而非日常闲聊问候）。"
    '仅输出 {"score": 0.0} 到 {"score": 1.0}，score 越高越需要回答。'
)

# quick-judge 结果类别：业务 true/false 可缓存；其余为技术失败，
# fail-closed（不触发群聊回复）且不得写入判定缓存。
# timeout/provider_error/invalid_json 为 awakening 层类别；service 层
# 技术失败（empty/length/provider_error/no_provider）直接透传其 outcome，
# 技术失败判定统一经 QuickJudgeResult.is_technical，不在此枚举字符串。
_JUDGE_BUSINESS_TRUE = "business_true"
_JUDGE_BUSINESS_FALSE = "business_false"
_JUDGE_TIMEOUT = "timeout"
_JUDGE_PROVIDER_ERROR = "provider_error"
_JUDGE_INVALID_JSON = "invalid_json"


@dataclass(slots=True)
class QuickJudgeOutcome:
    """awakening 层的 quick-judge 判定结果。

    ``triggered`` 为 None 表示技术失败（fail-closed）；诊断字段与
    QuickJudgeResult.to_diagnostic() 同源，另含解析状态，禁止携带
    聊天正文、prompt、模型原始响应、凭据或 endpoint。
    """

    category: str
    triggered: bool | None
    diagnostic: dict


def _parse_judge_text(text: str, threshold: float) -> bool | None:
    """严格解析业务判定；无法解析返回 None（区别于业务 false）。

    只接受完整 JSON 对象；残缺 JSON、散文中出现的 "trigger" 字样，以及
    score 值不可数值化（字符串/None/嵌套结构等）的输出一律视为不可解析
    （fail-closed，不写缓存）。
    """
    try:
        data = extract_json_object(text)
    except (TypeError, ValueError):
        return None
    if "score" in data:
        try:
            return float(data["score"]) >= threshold
        except (TypeError, ValueError):
            return None
    if "trigger" in data:
        trigger = data["trigger"]
        if isinstance(trigger, bool):
            return trigger
        if isinstance(trigger, str):
            return trigger.strip().lower() == "true"
        return bool(trigger)
    return None


@dataclass(frozen=True, slots=True)
class JudgeTarget:
    """判定目标的显式数据（仅诊断字段，无敏感信息）。"""

    provider_id: str
    model: str


@dataclass(frozen=True, slots=True)
class JudgeSettings:
    """一次判定所需的通道参数（orchestrator 单点解析后下传）。"""

    timeout: float
    max_tokens: int
    target: JudgeTarget


def _judge_target(config: JudgeTargetSource) -> JudgeTarget:
    qj = config.quick_judge
    provider_id = qj.provider_id or config.runtime.default_provider or ""
    return JudgeTarget(provider_id=str(provider_id), model=str(qj.model))


def resolve_judge_settings(config: JudgeTargetSource) -> JudgeSettings:
    """解析 quick_judge 通道参数；非法值（<=0）回退默认。"""
    qj = config.quick_judge
    return JudgeSettings(
        timeout=qj.timeout if qj.timeout > 0 else 2.0,
        max_tokens=qj.max_tokens if qj.max_tokens > 0 else 64,
        target=_judge_target(config),
    )


def cache_business_outcome(
    st: AwakeningState, rule: str, group_id: int | str, cache_text: str, outcome: QuickJudgeOutcome
) -> None:
    """仅业务 true/false 写入判定缓存；技术失败不缓存。"""
    if outcome.category == _JUDGE_BUSINESS_TRUE:
        st.llm_cache_set(rule, group_id, cache_text, True)
    elif outcome.category == _JUDGE_BUSINESS_FALSE:
        st.llm_cache_set(rule, group_id, cache_text, False)


async def llm_judge(
    svc: AwakeningJudgeChannel,
    system_prompt: str,
    user_prompt: str,
    threshold: float,
    timeout: float,
    max_tokens: int,
) -> QuickJudgeOutcome:
    """Call quick_judge with timeout; classify the outcome for cache/log policy."""
    # quick_judge uses its own system_prompt; we embed ours in the user prompt
    full_prompt = f"[系统指令] {system_prompt}\n\n[待判定内容] {user_prompt}"
    started = monotonic()
    target = _judge_target(svc.config)
    try:
        with usage_scope("awakening_judge"):
            result = await asyncio.wait_for(
                svc.quick_judge_detailed(full_prompt, max_tokens=max_tokens),
                timeout=timeout,
            )
    except asyncio.TimeoutError:
        diagnostic = {
            "outcome": _JUDGE_TIMEOUT,
            "duration_ms": round((monotonic() - started) * 1000, 2),
            "provider": target.provider_id,
            "model": target.model,
        }
        logger.warning("awakening: quick_judge timed out after %.1fs: %s", timeout, diagnostic)
        return QuickJudgeOutcome(_JUDGE_TIMEOUT, None, diagnostic)
    except Exception:
        diagnostic = {
            "outcome": _JUDGE_PROVIDER_ERROR,
            "duration_ms": round((monotonic() - started) * 1000, 2),
            "provider": target.provider_id,
            "model": target.model,
        }
        logger.warning("awakening: quick_judge call failed: %s", diagnostic, exc_info=True)
        return QuickJudgeOutcome(_JUDGE_PROVIDER_ERROR, None, diagnostic)

    diagnostic = result.to_diagnostic()
    if result.is_technical:
        logger.warning("awakening: quick_judge technical failure: %s", diagnostic)
        return QuickJudgeOutcome(result.outcome, None, diagnostic)

    parsed = _parse_judge_text(result.text, threshold)
    if parsed is None:
        merged = {**diagnostic, "parsed": False}
        logger.warning("awakening: quick_judge unparsable output: %s", merged)
        return QuickJudgeOutcome(_JUDGE_INVALID_JSON, None, merged)

    merged = {**diagnostic, "parsed": True}
    logger.debug("awakening: quick_judge resolved: %s", merged)
    return QuickJudgeOutcome(
        _JUDGE_BUSINESS_TRUE if parsed else _JUDGE_BUSINESS_FALSE, parsed, merged
    )


def llm_cache_text(message_text: str, threshold: float) -> str:
    return f"{threshold:.6g}\0{message_text}"
