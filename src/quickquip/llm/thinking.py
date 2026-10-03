"""思考档位归一化层：内部六档 → 各协议/后端 wire 参数（1.16.x 运行时切换 PR-B）。

内部词表六档（low/medium/high/xhigh/max/ultra，单源 config.REASONING_EFFORT_CHOICES），
调用方传入档位与 provider/model，本层返回 wire 注入指令（``ThinkingDirective``）或
None（不发送任何思考参数）。映射口径来自 2026-10 调研（dev/research
2026-10-03-reasoning-effort-runtime-switch §二）：

- openai chat：顶层 ``reasoning_effort``。三档系 DeepSeek/GLM-5.3/Kimi k3
  （medium→high、xhigh→high、max/ultra→max，DeepSeek 官方映射即此口径）；
  MiniMax 五档全集（ultra 降 max）；xAI 止于 xhigh；未知后端透传
  （ultra 一律降 max——ultra 是 Codex 订阅产品层档位，公开 API 词表止于
  max，D8）。DeepSeek 家族附带 ``thinking:{type:"enabled"}`` 开关。
- claude：4.7+ 走 ``thinking:{type:"adaptive"}`` + ``output_config.effort``
  （4.7+/5 系传旧式 type:"enabled" 直接 400）；Opus/Sonnet 4.6 有 max 无
  xhigh（xhigh 钳 high）；4.5 及更早走旧式 ``thinking.budget_tokens``
  固定值表（不按 max_tokens 比例换算），约束 budget ≥1024 且 <
  max_tokens。非 Claude 家族模型挂 claude 协议（Kimi/MiMo 兼容端点）不
  发送 + 节流日志 fail-visible。
- gemini：3.x 走 ``thinkingLevel``（low→LOW、medium→MEDIUM、high 及以上
  →HIGH）；2.5 走 ``thinkingBudget`` 固定值表；两者不可同传（上游 400）。
- openai_responses 不走本层：档位到 profile 词表的映射与降档收敛在
  ``provider/openai_responses/request.py`` 的 ``reasoning_control``
  （profile 即该协议的归一化层）。

钳制与不发送都经节流日志（每进程每组合一次）保持 fail-visible；命令层
反馈的「请求档 → 生效档」展示以 directive 的 requested_tier/clamped 为准。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from quickquip.llm.config import REASONING_EFFORT_CHOICES, ProviderConfig

logger = logging.getLogger(__name__)

# 内部六档序（与 config 词表同源）。
_TIER_ORDER = REASONING_EFFORT_CHOICES

# openai chat 家族钳制表（2026-10 调研 §二）。
_OPENAI_THREE_TIER = {
    "low": "low",
    "medium": "high",
    "high": "high",
    "xhigh": "high",
    "max": "max",
    "ultra": "max",
}
_OPENAI_FIVE_TIER = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "max": "max",
    "ultra": "max",
}
_OPENAI_XAI = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "max": "xhigh",
    "ultra": "xhigh",
}
_OPENAI_DEFAULT = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "max": "max",
    "ultra": "max",
}

# claude 旧式 budget 型号（4.5 及更早）固定值表：参照 rikkahub 固定值方案
# 不按 max_tokens 比例换算；Anthropic 要求 budget ≥1024，low 档 1000 收 1024。
_CLAUDE_BUDGET_TABLE = {
    "low": 1024,
    "medium": 2000,
    "high": 8000,
    "xhigh": 16000,
    "max": 32000,
    "ultra": 32000,
}
# budget 硬约束下界（Anthropic 契约）。
_CLAUDE_BUDGET_FLOOR = 1024

# gemini 2.5 thinkingBudget 固定值表（连续域 1–32768，表值均在界内）。
_GEMINI_BUDGET_TABLE = {
    "low": 1000,
    "medium": 2000,
    "high": 8000,
    "xhigh": 16000,
    "max": 32000,
    "ultra": 32000,
}

_GEMINI_LEVEL_MAP = {
    "low": "LOW",
    "medium": "MEDIUM",
    "high": "HIGH",
    "xhigh": "HIGH",
    "max": "HIGH",
    "ultra": "HIGH",
}

_CLAUDE_ADAPTIVE_FULL = dict(_OPENAI_FIVE_TIER)
_CLAUDE_ADAPTIVE_46 = {**_OPENAI_FIVE_TIER, "xhigh": "high"}

_CLAUDE_MODEL_RE = re.compile(r"^claude-(?:opus|sonnet|haiku)-(\d+)[.-](\d+)")
_GEMINI_MODEL_RE = re.compile(r"^gemini-(\d+)\.(\d+)")

# 节流日志：每进程每组合只记一次（钳制/不发送属配置面事件，无需逐请求重复）。
_logged_keys: set[tuple] = set()


def log_once(level: int, key: tuple, msg: str, *args) -> None:
    """节流日志：每进程每 key 只记一次（钳制/不发送属配置面事件）。"""
    if key in _logged_keys:
        return
    _logged_keys.add(key)
    logger.log(level, msg, *args)


@dataclass(frozen=True, slots=True)
class ThinkingDirective:
    """一档思考请求的 wire 注入指令。

    ``kind``：openai_effort（顶层 reasoning_effort）/ claude_adaptive
    （adaptive + output_config.effort）/ claude_budget（旧式
    budget_tokens）/ gemini_level（thinkingLevel）/ gemini_budget
    （thinkingBudget）。``requested_tier``/``clamped`` 供命令层反馈
    「请求档 → 生效档」。
    """

    kind: str
    effort: str | None = None
    budget_tokens: int | None = None
    # DeepSeek 家族需附带 thinking:{type:"enabled"} 开关才进入思考态。
    thinking_type_enabled: bool = False
    requested_tier: str = ""
    clamped: bool = False


def _model_family(model: str) -> str:
    """按 wire 模型名归家族（小写、去 provider 前缀如 openrouter 的 x-ai/）。"""
    name = model.strip().lower().rsplit("/", 1)[-1]
    if name.startswith("deepseek"):
        return "deepseek"
    if name.startswith("glm"):
        return "glm"
    if name.startswith(("kimi", "k2.", "k2-", "k3")):
        return "kimi"
    if name.startswith("minimax"):
        return "minimax"
    if name.startswith("grok"):
        return "xai"
    if name.startswith("claude"):
        return "claude"
    if name.startswith("gemini"):
        return "gemini"
    return ""


def _claude_generation(model: str) -> tuple[int, int] | None:
    """claude-opus-4-8 → (4, 8)；claude-haiku-4-5-20251001 → (4, 5)。"""
    match = _CLAUDE_MODEL_RE.match(model.strip().lower().rsplit("/", 1)[-1])
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _gemini_generation(model: str) -> tuple[int, int] | None:
    match = _GEMINI_MODEL_RE.match(model.strip().lower().rsplit("/", 1)[-1])
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _resolve_openai(tier: str, model: str) -> ThinkingDirective:
    family = _model_family(model)
    if family in ("deepseek", "glm", "kimi"):
        wire = _OPENAI_THREE_TIER[tier]
    elif family == "minimax":
        wire = _OPENAI_FIVE_TIER[tier]
    elif family == "xai":
        wire = _OPENAI_XAI[tier]
    else:
        wire = _OPENAI_DEFAULT[tier]
    return ThinkingDirective(
        kind="openai_effort",
        effort=wire,
        thinking_type_enabled=(family == "deepseek"),
        requested_tier=tier,
        clamped=(wire != tier),
    )


def _resolve_claude(
    tier: str, provider: ProviderConfig, model: str, max_output_tokens: int | None
) -> ThinkingDirective | None:
    if _model_family(model) != "claude":
        # 非 Claude 家族挂 claude 兼容协议（Kimi/MiMo 等）：其 Anthropic 形态
        # 端点对 thinking/effort 参数的支持面无实测依据，不发送 + fail-visible。
        log_once(
            logging.WARNING,
            ("claude-unsupported", provider.id, model),
            "provider %s 模型 %s 非 Claude 家族，claude 协议思考参数不发送（请求档 %s 未生效）",
            provider.id, model, tier,
        )
        return None
    gen = _claude_generation(model)
    if gen is not None and gen <= (4, 5):
        budget = _CLAUDE_BUDGET_TABLE[tier]
        if max_output_tokens is not None and budget >= max_output_tokens:
            budget = max_output_tokens - 1
        if budget < _CLAUDE_BUDGET_FLOOR:
            log_once(
                logging.WARNING,
                ("claude-budget-floor", provider.id, model, tier),
                "provider %s 模型 %s 档位 %s 换算 budget 受 max_tokens 钳到 %d 以下，放弃发送",
                provider.id, model, tier, _CLAUDE_BUDGET_FLOOR,
            )
            return None
        return ThinkingDirective(
            kind="claude_budget",
            budget_tokens=budget,
            requested_tier=tier,
            clamped=(budget != _CLAUDE_BUDGET_TABLE[tier]),
        )
    # 4.6 起走 adaptive；4.6（Opus/Sonnet）有 max 无 xhigh → 钳 high；
    # 不可解析代际的新型号按当前形态（adaptive）处理。
    table = _CLAUDE_ADAPTIVE_46 if gen == (4, 6) else _CLAUDE_ADAPTIVE_FULL
    wire = table[tier]
    return ThinkingDirective(
        kind="claude_adaptive", effort=wire, requested_tier=tier, clamped=(wire != tier)
    )


def _resolve_gemini(tier: str, provider: ProviderConfig, model: str) -> ThinkingDirective | None:
    if _model_family(model) != "gemini":
        log_once(
            logging.WARNING,
            ("gemini-unsupported", provider.id, model),
            "provider %s 模型 %s 非 Gemini 家族，gemini 协议思考参数不发送（请求档 %s 未生效）",
            provider.id, model, tier,
        )
        return None
    gen = _gemini_generation(model)
    if gen is not None and gen[0] == 2:
        return ThinkingDirective(
            kind="gemini_budget",
            budget_tokens=_GEMINI_BUDGET_TABLE[tier],
            requested_tier=tier,
            clamped=False,
        )
    # 3.x 及不可解析代际的新型号按当前形态（thinkingLevel）处理；按型号
    # 裁剪面（3.1 Pro 无 MINIMAL 等）与本表无交集（本层不发 MINIMAL）。
    return ThinkingDirective(
        kind="gemini_level",
        effort=_GEMINI_LEVEL_MAP[tier],
        requested_tier=tier,
        clamped=(_GEMINI_LEVEL_MAP[tier] != tier.upper()),
    )


def resolve_thinking(
    tier: str | None,
    provider: ProviderConfig,
    model: str,
    *,
    max_output_tokens: int | None = None,
) -> ThinkingDirective | None:
    """内部六档 → wire 注入指令；空档/无能力后端返回 None（不发送）。

    ``tier`` 为生效档位（调用方已完成 scope 覆盖解析）；空串/None 表示
    不发思考参数（模型默认档，现状语义）。非法档位抛 ValueError
    （配置校验已在加载期拦截，此处为直连构造的防御）。
    """
    tier = (tier or "").strip().lower()
    if not tier:
        return None
    if tier not in _TIER_ORDER:
        raise ValueError(f"未知思考档位 {tier!r}（可用：{'/'.join(_TIER_ORDER)}）")
    if provider.protocol == "openai":
        directive = _resolve_openai(tier, model)
    elif provider.protocol == "claude":
        directive = _resolve_claude(tier, provider, model, max_output_tokens)
    elif provider.protocol == "gemini":
        directive = _resolve_gemini(tier, provider, model)
    else:
        # openai_responses 走 profile 词表层（request.reasoning_control）。
        return None
    if directive is not None and directive.clamped:
        log_once(
            logging.INFO,
            ("clamped", provider.id, model, tier, directive.effort, directive.budget_tokens),
            "provider %s 模型 %s 思考档位 %s 钳制为 %s",
            provider.id, model, tier,
            directive.effort or f"budget={directive.budget_tokens}",
        )
    return directive
