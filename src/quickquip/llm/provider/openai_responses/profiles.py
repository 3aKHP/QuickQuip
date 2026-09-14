"""OpenAI Responses 协议的 profile 能力位与 wire 常量。

profile 是"有日期的兼容契约"：新能力不得改写既有 profile id 的行为，
新后端形状以新 profile id 进入注册表。首批两个（1.16 决策 2）：

- ``openai-public``：官方 ``/v1/responses`` 端点。
- ``codex-http-relay``：Codex 形态中转（HTTP+SSE）。差异点：不发
  ``service_tier``；容忍 ``codex.*`` 等中转私有结构事件；终态 ``output``
  可能缺省可选字段，以流式 ``output_item.done`` 的完整 item 为回放基准。

深搜/MiMo 式 stateless subset profile（无 ``store:false``、明文 reasoning）
未随首批引入；引入时在此补注册项与能力位，序列化/解析侧按能力位分支。
"""
from __future__ import annotations

from dataclasses import dataclass

from quickquip.llm.provider.base import LLMProviderError

# 与 llm.toml 的 protocol 值 / owner 记录的 protocol 字段同源。
OPENAI_RESPONSES_PROTOCOL = "openai_responses"

# QuickQuip 侧思考档位六档（1.16 决策 3）：到各 profile 实际 wire effort 的
# 映射集中 request.py 一处；本常量供配置校验与档位词表引用。
REASONING_EFFORT_TIERS = ("low", "medium", "high", "xhigh", "max", "ultra")


@dataclass(frozen=True, slots=True)
class ResponsesProfile:
    profile_id: str
    # profile 实际接受的 wire reasoning.effort 词表；六档映射结果必须落在
    # 该集合内，超出按降档规则收敛（见 request._REASONING_EFFORT_MAP）。
    wire_efforts: frozenset[str]
    # 请求 service_tier 字段值；None = 不发送。
    service_tier: str | None
    # 容忍中转私有结构事件（codex.rate_limits 等，见 stream.py）。
    tolerate_relay_events: bool
    # 终态 output 与流式 output_item.done 逐项子集核对后以流式为准。
    reconcile_relay_items: bool


PROFILES: dict[str, ResponsesProfile] = {
    "openai-public": ResponsesProfile(
        profile_id="openai-public",
        wire_efforts=frozenset({"low", "medium", "high", "xhigh"}),
        service_tier="auto",
        tolerate_relay_events=False,
        reconcile_relay_items=False,
    ),
    "codex-http-relay": ResponsesProfile(
        profile_id="codex-http-relay",
        wire_efforts=frozenset({"low", "medium", "high", "xhigh"}),
        service_tier=None,
        tolerate_relay_events=True,
        reconcile_relay_items=True,
    ),
}

DEFAULT_PROFILE_ID = "openai-public"


def resolve_profile(profile_id: str) -> ResponsesProfile:
    """按 id 解析 profile；未知 id fail-closed（中转形状漂移必须显式失败）。"""
    profile = PROFILES.get(profile_id)
    if profile is None:
        known = ", ".join(sorted(PROFILES))
        raise LLMProviderError(
            f"未知的 openai_responses profile：{profile_id!r}（可用：{known}）"
        )
    return profile
