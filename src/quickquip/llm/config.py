from __future__ import annotations

from quickquip.llm.client_fingerprints.catalog import FingerprintRuntime

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any

from quickquip.llm.epoch import EpochParams

logger = logging.getLogger(__name__)

MAX_IMAGE_PREPROCESSING_TOKENS = 2048

# 上游 429/5xx 自动重试默认策略：RuntimeConfig / ProviderConfig 字段默认值、
# 请求配置与 RetryPolicy 字段默认值均单点引用此组常量
DEFAULT_RETRY_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BASE_DELAY = 1.0
DEFAULT_RETRY_JITTER = 0.5

# agent_replay_loop_tokens 的解析钳制界（runtime 与 provider 覆盖共用；
# request_budget 的推导下限/上限同源引用）。
AGENT_REPLAY_LOOP_TOKENS_FLOOR = 512
AGENT_REPLAY_LOOP_TOKENS_CEILING = 4_194_304

# 单请求内联媒体（解码后）总字节预算缺省（issue #228；2026-09 生产事故后
# 调整为与 media_guard 单图解码上限对齐的 5MiB）：过小阈值会整图丢弃正常
# 尺寸的引用大图（教材扫描/长截图常态超限）；超出额度的媒体先经降采样
# 重编码压入预算，仅压缩仍不达标时才丢弃。该值同时决定请求体上限
# （base64 膨胀约 4/3，5MiB 解码量对应最坏约 6.7MiB 请求体）：上游网关
# 若按更紧的请求体或 token 口径风控（部分网关把图片 base64 按文本估算
# token），应显式配置更小的 provider 级值。max_inline_media_bytes 可覆盖；
# 0 = 不限。
DEFAULT_MAX_INLINE_MEDIA_BYTES = 5 * 1024 * 1024


@dataclass(slots=True)
class TriggerConfig:
    default_prefix: str = "/ai"
    allow_prefix: bool = True
    allow_at: bool = True
    empty_prompt_reply: str = "请在触发指令或艾特后面补上想说的话。"


@dataclass(slots=True)
class AutoSearchConfig:
    enabled: bool = False
    search_max_calls_per_round: int = 3


@dataclass(slots=True)
class QuickJudgeConfig:
    provider_id: str = ""
    model: str = ""
    timeout: float = 2.0
    max_tokens: int = 64


@dataclass(slots=True)
class RuntimeConfig:
    enabled: bool = False
    memory_enabled: bool = True
    default_provider: str | None = None
    default_persona: str | None = None
    history_limit: int = 10
    history_max_messages_per_group: int = 40
    memory_limit: int = 6
    memory_max_items_per_group: int = 200
    max_prompt_chars: int = 4000
    tool_calling_enabled: bool = False
    tool_max_rounds: int = 8
    tool_max_calls_per_round: int = 16
    retry_max_attempts: int = DEFAULT_RETRY_MAX_ATTEMPTS
    retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY
    retry_jitter: float = DEFAULT_RETRY_JITTER
    auto_memory_enabled: bool = False
    auto_memory_prompt: str = ""
    auto_memory_max_tokens: int = 256
    # ── 会话纪元参数（全局缺省；[[providers]] 同名键可覆盖） ──────────
    # context_tokens 是标尺而非阈值：懒初始化与 /llm use 新键的锚点跨度。
    # T 宁短勿长：设短退化为滚动窗形态，设长则每轮全价且窗口更长。
    epoch_context_tokens: int = 8000
    epoch_cold_idle_seconds: int = 300
    epoch_cold_target_tokens: int = 4000
    epoch_cold_trigger_tokens: int = 5000
    epoch_hot_target_tokens: int = 32000
    epoch_cap_tokens: int = 64000
    # ── 【现场】补丁（近期消息缓冲的 LLM 服役口径；仅全局，无 provider 覆盖） ──
    recent_context_token_budget: int = 800
    recent_context_floor_seconds: int = 300
    # 应用侧输入预算（§8.3）：显式与内置窗口表均未解析到模型容量
    # （capacity unknown）时的缺省与兜底；可被 provider 覆盖（非正数视为
    # 未配置），容量已知时按窗口推导优先。
    request_input_token_budget: int = 96_000
    # D5 关闭 Loop 保留三上限（§2）：先触顶者触发整 Loop 清理。
    agent_record_retention_days: int = 30
    agent_record_max_loops_per_scope: int = 1000
    agent_record_max_bytes_per_scope: int = 67_108_864
    # 逐 Turn 交付上线开关（§6.3）：默认关闭——安装新版本不立刻增加群内
    # 消息数；记录与投影始终工作。两域独立：中间轮正文是否发送、最终
    # 正文是否走 sink 自然分段（关闭时沿旧单发路径）。
    agent_delivery_intermediate_enabled: bool = False
    agent_delivery_final_enabled: bool = False
    # 历史重放投影预算（§8.2）：推导下限（512..4MiB）。实际预算由
    # request_budget.derive_replay_budget 从请求输入预算（仲裁者）推导；
    # provider 覆盖键为硬值，capacity unknown 时本值即实际值。
    agent_replay_loop_tokens: int = 4096
    reply_split_threshold_chars: int = 800
    reply_chunk_max_chars: int = 1200
    reply_send_interval_ms: int = 800
    reply_max_chunks_per_loop: int = 64
    # 出站「@名字」艾特的同目标冷却秒数：窗内重复艾特同一人降级为纯文本（0 关闭冷却）。
    mention_cooldown_seconds: float = 600.0

    client_cluster: str = ""


@dataclass(slots=True)
class ToolsConfig:
    enabled: list[str] = field(default_factory=list)
    # enabled 列表的作用模式：append = 在默认白名单 + MCP 工具之上追加
    # （默认，opt-in 工具的启用路径）；replace = 精确过滤，只暴露所列工具
    enabled_mode: str = "append"  # append | replace
    discovery_mode: str = "auto"  # off | on | auto
    discovery_min_tools: int = 10
    discovery_search_limit: int = 5
    discovery_max_loaded_tools: int = 12
    always_loaded: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SkillsConfig:
    """[skills] 段：Skill 目录与 4 个 skill 工具的资源/安全上限。"""

    enabled: bool = True
    # 空 = 默认项目根 skills/；相对路径按项目根解析。
    catalog_dir: str = ""
    catalog_max_bytes: int = 8192
    resource_max_bytes: int = 65536
    search_max_results: int = 50
    search_max_output_bytes: int = 32768
    script_timeout_ms: int = 30000
    script_max_output_bytes: int = 65536


@dataclass(slots=True)
class MCPServerConfig:
    id: str
    transport: str = "stdio"
    enabled: bool = True
    timeout_seconds: float = 30.0
    protocol_version: str = "2025-03-26"
    tool_prefix: str | None = None
    include_tools: list[str] = field(default_factory=list)
    exclude_tools: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    command: str = ""
    args: list[str] = field(default_factory=list)
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    image: str = ""
    docker_command: str = "docker"
    docker_args: list[str] = field(default_factory=list)
    pull_policy: str = "missing"  # always | missing | never
    mounts: list[str] = field(default_factory=list)
    network: str | None = None
    container_workdir: str | None = None
    negotiation: str = "legacy"  # legacy | auto | modern
    supported_protocol_versions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MCPConfig:
    enabled: bool = False
    servers: list[MCPServerConfig] = field(default_factory=list)


@dataclass(slots=True)
class PersonaConfig:
    id: str
    display_name: str
    system_prompt: str
    style_prompt: str = ""
    scope: list[str] = field(default_factory=list)  # empty = both group and private
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ImagePreprocessingConfig:
    enabled: bool = False
    provider_id: str = ""
    model: str = ""
    max_tokens: int = 300
    temperature: float = 0.3
    prompt: str = ""


# 群聊用户可见的"当前 provider 已禁用"提示：回复主链 / 单发命令 / 当前探活共用，勿在各处另行拼装
DISABLED_PROVIDER_REPLY = (
    "当前 provider 已禁用：{provider_id}（enabled = false），请用 /llm use 切换其他 provider。"
)


# openai_responses 配置词表（单一事实来源）：profile 注册表与六档映射
# （provider/openai_responses/）从本模块取词表——config 不能 import
# provider 包（base.py 依赖 config，反向才不构成环），守护测试断言两侧相等。
RESPONSES_PROFILE_IDS = frozenset({"openai-public", "codex-http-relay"})
REASONING_EFFORT_CHOICES = ("low", "medium", "high", "xhigh", "max", "ultra")
DEFAULT_RESPONSES_PROFILE_ID = "openai-public"


@dataclass(slots=True)
class ProviderConfig:
    id: str
    protocol: str
    base_url: str
    api_key_env: str
    default_model: str
    models: list[str]
    enabled: bool = True  # false = 暂时禁用：不展示、不探活、cascade 跳过、拒绝切换
    client_fingerprint: str = "default"
    fingerprint_runtime: FingerprintRuntime | None = None
    non_vision_models: list[str] = field(default_factory=list)
    timeout_seconds: float = 45.0
    temperature: float = 0.8
    max_output_tokens: int = 800
    style_overrides: str = ""
    stream_enabled: bool = True
    headers: dict[str, str] = field(default_factory=dict)
    user_agent: str = ""
    extra_body: dict[str, Any] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    fallback_urls: list[str] = field(default_factory=list)
    proxy: str = ""
    prompt_caching: bool = False
    cache_ttl: str = ""  # Claude prompt-cache TTL；空=默认 5min，"1h"=扩展缓存
    auth_method: str = "api_key"  # "api_key" | "bearer"
    builtin_search: bool = False  # 声明 provider 原生搜索工具；仅 gemini 协议有请求级效果
    # openai_responses 专属：后端能力位 profile。词表单源
    # RESPONSES_PROFILE_IDS / DEFAULT_RESPONSES_PROFILE_ID（provider/
    # openai_responses/profiles.py 反向引用）。
    responses_profile: str = DEFAULT_RESPONSES_PROFILE_ID
    # 思考档位（全协议生效），词表单源 REASONING_EFFORT_CHOICES；留空 =
    # 不发思考参数 = 模型默认档。到各协议 wire 参数的翻译与钳制集中在
    # thinking.resolve_thinking（openai_responses 走其 profile 词表层）。
    # 独立于已废弃的 thinking_budget 数字口径（LLMRequest 兼容字段，
    # 主链路从未接线）。
    reasoning_effort: str = ""
    # 上游 429/5xx 自动重试策略；渠道与模型可覆盖全局缺省
    retry_max_attempts: int = DEFAULT_RETRY_MAX_ATTEMPTS
    retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY
    retry_jitter: float = DEFAULT_RETRY_JITTER
    # 会话纪元参数的 provider 级覆盖；None = 继承 [runtime] 全局缺省。
    # 解析合并见 LLMConfig.resolve_epoch_params（不走 retry 的就地盖章范式）。
    epoch_context_tokens: int | None = None
    epoch_cold_idle_seconds: int | None = None
    epoch_cold_target_tokens: int | None = None
    epoch_cold_trigger_tokens: int | None = None
    epoch_hot_target_tokens: int | None = None
    epoch_cap_tokens: int | None = None
    # 应用侧输入预算（§8.3）：provider 覆盖 None = 继承 runtime 缺省。
    request_input_token_budget: int | None = None
    # 单请求内联媒体（解码后）总字节预算；0 = 不限。
    # 收口逻辑见 provider/media_guard.py。
    max_inline_media_bytes: int = DEFAULT_MAX_INLINE_MEDIA_BYTES
    # 历史重放投影预算的 provider 级硬覆盖（§8.2）；None = 推导
    # （仲裁者减固定开销，runtime.agent_replay_loop_tokens 为下限）。
    agent_replay_loop_tokens: int | None = None
    # wire model -> token 容量；显式配置永远优先，未命中时按
    # context_windows 内置策展表解析，均未命中按 capacity unknown 处理。
    model_context_windows: dict[str, int] = field(default_factory=dict)
    model_parameters: dict[str, dict[str, Any]] = field(default_factory=dict)
    model_enabled: dict[str, bool] = field(default_factory=dict)
    style_profile: str = ""
    style_append: str | None = None


def provider_builtin_search_active(provider: ProviderConfig) -> bool:
    """builtin_search 的生效谓词：仅在 gemini 协议下有请求级效果。

    请求声明、search_web 工具互斥与健康检查都以本函数为单一判定来源，
    避免各消费点自行重复协议判断。
    """
    return provider.builtin_search and provider.protocol == "gemini"


@dataclass(slots=True)
class PricingRates:
    """价格规则的每百万 token 单价。

    cache_read/write_per_mtok 为 None 表示该桶无单独价（套餐制/无缓存溢价），
    计算时回退 input 价。
    """

    input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0
    cache_read_per_mtok: float | None = None
    cache_write_per_mtok: float | None = None
    source: str = "config"
    confidence: str = "configured"


@dataclass(slots=True)
class DailySummaryConfig:
    enabled: bool = False
    generate_cron: str = "0 6 * * *"
    publish_cron: str = "0 12 * * *"
    min_messages: int = 30
    summary_length_hint: int = 2000
    model_cascade: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DailyBriefingConfig:
    enabled: bool = False
    morning_cron: str = "0 8 * * *"
    noon_cron: str = "0 12 * * *"
    evening_cron: str = "0 22 * * *"
    min_messages_for_llm: int = 5
    active_users_limit: int = 5
    hot_words_limit: int = 5
    sample_messages_limit: int = 60
    max_context_chars: int = 40000
    max_output_chars: int = 320
    model_cascade: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WeeklyReportConfig:
    """群周报：每周自动生成上周群聊回顾。

    数据源为聊天归档（chat_archive，always-on），1.15.2 起全量消息进
    压缩序列化器后一次成文（日分节/分钟块/连发合并），不再按天采样；
    溢出由级联每跳字符预算兜底。period 标识为 ISO 周号（如 2026-W24）。
    """

    enabled: bool = False
    generate_cron: str = "0 9 * * 1"  # 每周一 09:00 生成上周周报
    publish_cron: str = "0 10 * * *"  # 每天 10:00 发布（周一发新报告，其余日子补发未发布的）
    min_messages: int = 100
    length_hint: int = 2000
    model_cascade: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MonthlyReportConfig:
    """群月报：每月自动生成上月群聊回顾。period 标识为 YYYY-MM（如 2026-06）。"""

    enabled: bool = False
    generate_cron: str = "0 9 1 * *"  # 每月 1 日 09:00 生成上月月报
    publish_cron: str = "0 10 * * *"  # 每天 10:00 发布（1 日发新报告，其余日子补发未发布的）
    min_messages: int = 300
    length_hint: int = 2500
    # 终稿聊天记录字符预算（中文约 1 字 ≈ 1 token 时 ≥200k token）。
    # 分周公平分配，周内高活跃日优先整日保留。
    input_char_budget: int = 240_000
    model_cascade: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LLMConfig:
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    triggers: TriggerConfig = field(default_factory=TriggerConfig)
    auto_search: AutoSearchConfig = field(default_factory=AutoSearchConfig)
    quick_judge: QuickJudgeConfig = field(default_factory=QuickJudgeConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    personas: dict[str, PersonaConfig] = field(default_factory=dict)
    daily_summary: DailySummaryConfig = field(default_factory=DailySummaryConfig)
    daily_briefing: DailyBriefingConfig = field(default_factory=DailyBriefingConfig)
    weekly_report: WeeklyReportConfig = field(default_factory=WeeklyReportConfig)
    monthly_report: MonthlyReportConfig = field(default_factory=MonthlyReportConfig)
    image_preprocessing: ImagePreprocessingConfig = field(default_factory=ImagePreprocessingConfig)
    style_profiles: dict[str, str] = field(default_factory=dict)
    pricing: dict[str, PricingRates] = field(default_factory=dict)
    pricing_references: dict[tuple[str | None, str], PricingRates] = field(default_factory=dict)
    revision: int = 0
    load_error: str | None = None
    source_path: Path | None = None

    @property
    def is_available(self) -> bool:
        return self.load_error is None and self.runtime.enabled and bool(self.providers)

    def resolve_epoch_params(self, provider: ProviderConfig | None = None) -> "EpochParams":
        """合并 [runtime] 全局缺省与 provider 级覆盖，产出纪元生效参数。

        关系非法（需 ``0 < cold_target < cold_trigger ≤ hot_target < cap``
        且 ``context_tokens > 0``、``cold_idle_seconds >= 0``）时：provider
        覆盖回退 runtime 值，runtime 值回退内置默认；均告警不致命。
        """
        base = EpochParams(
            context_tokens=self.runtime.epoch_context_tokens,
            cold_idle_seconds=self.runtime.epoch_cold_idle_seconds,
            cold_target_tokens=self.runtime.epoch_cold_target_tokens,
            cold_trigger_tokens=self.runtime.epoch_cold_trigger_tokens,
            hot_target_tokens=self.runtime.epoch_hot_target_tokens,
            cap_tokens=self.runtime.epoch_cap_tokens,
        )
        if not _epoch_params_valid(base):
            logger.warning("[runtime] epoch_* 参数关系非法，回退内置默认值")
            base = EpochParams()
        if provider is None:
            return base
        overrides = {}
        for config_field, param_field in _EPOCH_OVERRIDE_PAIRS:
            value = getattr(provider, config_field)
            overrides[param_field] = getattr(base, param_field) if value is None else value
        merged = EpochParams(**overrides)
        if not _epoch_params_valid(merged):
            logger.warning(
                "provider %s 的 epoch_* 覆盖参数关系非法，回退 [runtime] 值", provider.id
            )
            return base
        return merged


# (ProviderConfig 覆盖键, EpochParams 字段) 映射——新增纪元参数时只需加一行
_EPOCH_OVERRIDE_PAIRS = (
    ("epoch_context_tokens", "context_tokens"),
    ("epoch_cold_idle_seconds", "cold_idle_seconds"),
    ("epoch_cold_target_tokens", "cold_target_tokens"),
    ("epoch_cold_trigger_tokens", "cold_trigger_tokens"),
    ("epoch_hot_target_tokens", "hot_target_tokens"),
    ("epoch_cap_tokens", "cap_tokens"),
)


def _epoch_params_valid(params: "EpochParams") -> bool:
    return (
        params.context_tokens > 0
        and params.cold_idle_seconds >= 0
        and 0
        < params.cold_target_tokens
        < params.cold_trigger_tokens
        <= params.hot_target_tokens
        < params.cap_tokens
    )


_KNOWN_PERSONA_KEYS = {"id", "display_name", "system_prompt", "style_prompt", "scope"}


def load_llm_config(path: str | Path) -> LLMConfig:
    """Load legacy TOML for migration tooling and compatibility tests."""
    from quickquip.llm.config_legacy import load_llm_config as load_legacy

    return load_legacy(path)


def load_personas_only(config_path: str | Path) -> dict[str, PersonaConfig]:
    """Load independent persona files from the configuration directory."""
    from quickquip.llm.personas import load_personas

    return load_personas(Path(config_path).parent / "personas")
