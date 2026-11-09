"""OpenAI Responses 协议的 profile 能力位与 wire 常量。

profile 是"有日期的兼容契约"：新能力不得改写既有 profile id 的行为，
新后端形状以新 profile id 进入注册表。首批两个（1.16 决策 2）：

- ``openai-public``：官方 ``/v1/responses`` 端点。
- ``codex-http-relay``：Codex 形态中转（HTTP+SSE）。差异点：不发
  ``service_tier``；识别 ``codex.*`` 等预期附加事件并静默忽略；终态 ``output``
  可能缺省可选字段，以流式 ``output_item.done`` 的完整 item 为回放基准。
- ``codex-relay-hosted-tools``：在 ``codex-http-relay`` 全部能力位之上，
  由客户端显式声明 hosted 内置工具（2026-11-09 中转注入回归适配，见
  该注册项注记）。

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
    # 该集合内，超出按降档规则收敛（见 request.reasoning_control）。
    wire_efforts: frozenset[str]
    # 请求 service_tier 字段值；None = 不发送。
    service_tier: str | None
    # 将中转附加事件识别为预期事件；其他事件走共用的限量记录与忽略策略。
    recognize_relay_events: bool
    # 终态 output 与流式 output_item.done 逐项子集核对后以流式为准。
    reconcile_relay_items: bool
    # 客户端在 tools 数组显式声明的 hosted 内置工具类型集合；空 = 不声明。
    # wire 形状映射单源 request.HOSTED_TOOL_WIRE（与 wire_efforts 同构）。
    hosted_tools: frozenset[str] = frozenset()


PROFILES: dict[str, ResponsesProfile] = {
    "openai-public": ResponsesProfile(
        profile_id="openai-public",
        # 官方 API 的 effort 词表按 2026-09 已核对范围收敛（low..xhigh）；
        # 官方端点实测六档全支持后放开。
        wire_efforts=frozenset({"low", "medium", "high", "xhigh"}),
        service_tier="auto",
        recognize_relay_events=False,
        reconcile_relay_items=False,
    ),
    "codex-http-relay": ResponsesProfile(
        profile_id="codex-http-relay",
        # Codex 形态中转 gpt-6 / gpt-5.6 系五档恒等（low..max）。Codex 客户端
        # 目录对 sol/terra/astra 登记六档（含 ultra）、luna 系止于 max，但
        # 2026-10-03 实测中转网关校验层拒绝 ultra（HTTP 400，合法值止于
        # max）——网关能力位登记与 wire 透传是两回事，按实测收敛五档；
        # ultra 经降档规则落 max（ultra 语义为 max 级预算 + 服务端多代理
        # 编排，juice 与 max 相同，无实际能力损失）。
        wire_efforts=frozenset({"low", "medium", "high", "xhigh", "max"}),
        service_tier=None,
        recognize_relay_events=True,
        reconcile_relay_items=True,
    ),
    # 2026-11-09 起 CLIProxyAPI ≥8.0.57 的 ensureImageGenerationTool 注入被
    # 模型级 use_responses_lite 目录判定无条件跳过，标准协议请求被连坐，
    # 对话内生图静默失效（上游 issue router-for-me/CLIProxyAPI#7384）。本档
    # 让客户端按 Responses 协议正统形态显式声明 hosted 工具，替代中转的
    # 兼容注入层。上游修复后长期保留：注入自带去重，wire 上仍只有一份工具；
    # 回退 = config 修订把 profile id 切回 codex-http-relay。
    "codex-relay-hosted-tools": ResponsesProfile(
        profile_id="codex-relay-hosted-tools",
        # 四个能力位与 codex-http-relay 逐位相等（完整继承；守护测试
        # test_codex_relay_hosted_tools_inherits_relay_bits 断言不漂移）。
        wire_efforts=frozenset({"low", "medium", "high", "xhigh", "max"}),
        service_tier=None,
        recognize_relay_events=True,
        reconcile_relay_items=True,
        hosted_tools=frozenset({"image_generation"}),
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
