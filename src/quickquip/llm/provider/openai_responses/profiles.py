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

from quickquip.llm.config import (
    DEFAULT_RESPONSES_PROFILE_ID,
    REASONING_EFFORT_CHOICES,
)
from quickquip.llm.provider.base import LLMProviderError

# 与 llm.toml 的 protocol 值 / owner 记录的 protocol 字段同源。
OPENAI_RESPONSES_PROTOCOL = "openai_responses"

# QuickQuip 侧思考档位六档（1.16 决策 3）：词表单源 config（本模块反向
# 引用，config 不能 import provider 包）；到各 profile 实际 wire effort 的
# 映射集中 request.py 一处。注册表键集与 config.RESPONSES_PROFILE_IDS
# 的一致性由 test_provider_openai_responses 的守护测试断言。
REASONING_EFFORT_TIERS = REASONING_EFFORT_CHOICES
# 档位从低到高序（与词表同源）：六档超出 profile 词表时降档到其声明
# 的最高档（降档规则见 request.reasoning_control，词表即降档边界）。
_EFFORT_ORDER = REASONING_EFFORT_TIERS
DEFAULT_PROFILE_ID = DEFAULT_RESPONSES_PROFILE_ID


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
        # 官方 API 的 effort 词表按 2026-09 已核对范围收敛（low..xhigh）；
        # 官方端点实测六档全支持后放开。
        wire_efforts=frozenset({"low", "medium", "high", "xhigh"}),
        service_tier="auto",
        tolerate_relay_events=False,
        reconcile_relay_items=False,
    ),
    "codex-http-relay": ResponsesProfile(
        profile_id="codex-http-relay",
        # AGW/CPA 中转的 gpt-6 / gpt-5.6 系六档全支持（2026-09-14 按
        # 服务器网关能力位核对），恒等映射不降档。
        wire_efforts=frozenset(REASONING_EFFORT_TIERS),
        service_tier=None,
        tolerate_relay_events=True,
        reconcile_relay_items=True,
    ),
}

def resolve_profile(profile_id: str) -> ResponsesProfile:
    """按 id 解析 profile；未知 id fail-closed（中转形状漂移必须显式失败）。"""
    profile = PROFILES.get(profile_id)
    if profile is None:
        known = ", ".join(sorted(PROFILES))
        raise LLMProviderError(
            f"未知的 openai_responses profile：{profile_id!r}（可用：{known}）"
        )
    return profile
