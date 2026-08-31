from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any
import tomllib

from quickquip.common.config_utils import as_bool, as_dict, expand_env_value

logger = logging.getLogger(__name__)

MAX_IMAGE_PREPROCESSING_TOKENS = 2048


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
    retry_max_attempts: int = 3
    retry_base_delay: float = 1.0
    auto_memory_enabled: bool = False
    auto_memory_prompt: str = ""
    auto_memory_max_tokens: int = 256


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
DISABLED_PROVIDER_REPLY = "当前 provider 已禁用：{provider_id}（enabled = false），请用 /llm use 切换其他 provider。"


@dataclass(slots=True)
class ProviderConfig:
    id: str
    protocol: str
    base_url: str
    api_key_env: str
    default_model: str
    models: list[str]
    enabled: bool = True  # false = 暂时禁用：不展示、不探活、cascade 跳过、拒绝切换
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


def provider_builtin_search_active(provider: ProviderConfig) -> bool:
    """builtin_search 的生效谓词：仅在 gemini 协议下有请求级效果。

    请求声明、search_web 工具互斥与健康检查都以本函数为单一判定来源，
    避免各消费点自行重复协议判断。
    """
    return provider.builtin_search and provider.protocol == "gemini"


@dataclass(slots=True)
class PricingRates:
    """单个模型的 per-MTok 定价（llm.toml [pricing.models.<name>]）。

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

    数据源复用 wordcloud collector（always-on，不删除），按天采样后套用日报同款 LLM 管线。
    period 标识为 ISO 周号（如 2026-W24）。
    """

    enabled: bool = False
    generate_cron: str = "0 9 * * 1"  # 每周一 09:00 生成上周周报
    publish_cron: str = "0 10 * * *"  # 每天 10:00 发布（周一发新报告，其余日子补发未发布的）
    min_messages: int = 100
    length_hint: int = 2000
    sample_per_day: int = 50  # 每天采样消息数上限，控制总量
    model_cascade: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MonthlyReportConfig:
    """群月报：每月自动生成上月群聊回顾。period 标识为 YYYY-MM（如 2026-06）。"""

    enabled: bool = False
    generate_cron: str = "0 9 1 * *"  # 每月 1 日 09:00 生成上月月报
    publish_cron: str = "0 10 * * *"  # 每天 10:00 发布（1 日发新报告，其余日子补发未发布的）
    min_messages: int = 300
    length_hint: int = 2500
    sample_per_day: int = 20  # 月报跨度长，每天采样更少
    model_cascade: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LLMConfig:
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    triggers: TriggerConfig = field(default_factory=TriggerConfig)
    auto_search: AutoSearchConfig = field(default_factory=AutoSearchConfig)
    quick_judge: QuickJudgeConfig = field(default_factory=QuickJudgeConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
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
    load_error: str | None = None
    source_path: Path | None = None

    @property
    def is_available(self) -> bool:
        return self.load_error is None and self.runtime.enabled and bool(self.providers)

_KNOWN_PERSONA_KEYS = {"id", "display_name", "system_prompt", "style_prompt", "scope"}


def _read_personas(raw_personas: list[dict[str, Any]]) -> dict[str, PersonaConfig]:
    personas: dict[str, PersonaConfig] = {}
    for entry in raw_personas:
        entry = expand_env_value(entry)
        persona_id = str(entry.get("id", "")).strip()
        if not persona_id:
            continue
        raw_scope = entry.get("scope", [])
        if isinstance(raw_scope, str):
            raw_scope = [raw_scope]
        parsed_scope = [s for s in (str(s).strip().lower() for s in raw_scope) if s in {"group", "private"}]
        extras = {k: v for k, v in entry.items() if k not in _KNOWN_PERSONA_KEYS}
        personas[persona_id] = PersonaConfig(
            id=persona_id,
            display_name=str(entry.get("display_name", persona_id)).strip() or persona_id,
            system_prompt=str(entry.get("system_prompt", "")).strip(),
            style_prompt=str(entry.get("style_prompt", "")).strip(),
            scope=parsed_scope,
            extras=extras,
        )
    return personas


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_pricing(raw: dict[str, Any]) -> dict[str, PricingRates]:
    """解析 [pricing.models.<name>] 子表为 {model: PricingRates}。"""
    models_raw = as_dict(raw.get("models"))
    pricing: dict[str, PricingRates] = {}
    for model_name, entry in models_raw.items():
        name = str(model_name).strip()
        if not name or not isinstance(entry, dict):
            continue
        pricing[name] = PricingRates(
            input_per_mtok=float(entry.get("input_per_mtok", 0.0) or 0.0),
            output_per_mtok=float(entry.get("output_per_mtok", 0.0) or 0.0),
            cache_read_per_mtok=_optional_float(entry.get("cache_read_per_mtok")),
            cache_write_per_mtok=_optional_float(entry.get("cache_write_per_mtok")),
            source=str(entry.get("source", "config")).strip() or "config",
            confidence=str(entry.get("confidence", "configured")).strip() or "configured",
        )
    return pricing


def _load_personas_from_dir(personas_dir: Path) -> list[dict[str, Any]]:
    """Load personas from a directory of TOML files.

    Each file may define a persona using flat top-level keys (id, display_name,
    system_prompt, style_prompt, plus any extras), or via a [[personas]] array
    for compatibility.

    A special file ``_shared.toml`` may define:
    - ``shared_system_prompt``: appended to every persona's system_prompt
    - ``shared_style_prompt``: appended to every persona's style_prompt

    Files are loaded in lexicographic order. ``_shared.toml`` is processed
    first and never treated as a persona definition itself.
    """
    if not personas_dir.is_dir():
        return []

    # Load shared rules first
    shared_system = ""
    shared_style = ""
    shared_path = personas_dir / "_shared.toml"
    if shared_path.exists():
        try:
            with shared_path.open("rb") as fh:
                shared_data = tomllib.load(fh)
            shared_system = str(shared_data.get("shared_system_prompt", "")).strip()
            shared_style = str(shared_data.get("shared_style_prompt", "")).strip()
        except tomllib.TOMLDecodeError as exc:
            logger.warning("跳过损坏的 _shared.toml：%s", exc)

    personas: list[dict[str, Any]] = []
    for toml_file in sorted(personas_dir.glob("*.toml")):
        if toml_file.name.startswith("_"):
            continue  # skip _shared.toml and other reserved files
        try:
            with toml_file.open("rb") as fh:
                data = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            logger.warning("跳过损坏的人格文件 %s：%s", toml_file.name, exc)
            continue

        # Support flat top-level keys (preferred) or [[personas]] array
        if "id" in data:
            entry = dict(data)
            # Inject shared content
            if shared_system:
                existing = str(entry.get("system_prompt", "")).rstrip()
                entry["system_prompt"] = (existing + "\n\n" + shared_system).lstrip() if existing else shared_system
            if shared_style:
                existing = str(entry.get("style_prompt", "")).rstrip()
                entry["style_prompt"] = (existing + "\n\n" + shared_style).lstrip() if existing else shared_style
            personas.append(entry)
        elif "personas" in data:
            for entry in data["personas"]:
                entry = dict(entry)
                if shared_system:
                    existing = str(entry.get("system_prompt", "")).rstrip()
                    entry["system_prompt"] = (existing + "\n\n" + shared_system).lstrip() if existing else shared_system
                if shared_style:
                    existing = str(entry.get("style_prompt", "")).rstrip()
                    entry["style_prompt"] = (existing + "\n\n" + shared_style).lstrip() if existing else shared_style
                personas.append(entry)

    return personas


def _read_providers(raw_providers: list[dict[str, Any]], *, style_profiles: dict[str, str] | None = None) -> dict[str, ProviderConfig]:
    style_profiles = style_profiles or {}
    providers: dict[str, ProviderConfig] = {}
    for entry in raw_providers:
        entry = expand_env_value(entry)
        provider_id = str(entry.get("id", "")).strip()
        if not provider_id:
            continue

        try:
            provider = _parse_single_provider(entry, provider_id, style_profiles)
        except Exception:
            logger.exception("跳过配置无效的 provider %s", provider_id)
            continue
        providers[provider_id] = provider
    return providers


def _parse_single_provider(
    entry: dict[str, Any], provider_id: str, style_profiles: dict[str, str]
) -> ProviderConfig:
    raw_headers = as_dict(entry.get("headers"))

    style_text = str(entry.get("style_overrides", "")).strip()
    profile_name = str(entry.get("style_profile", "")).strip()
    if profile_name:
        if profile_name not in style_profiles:
            available = ", ".join(sorted(style_profiles)) if style_profiles else "(无)"
            logger.error(
                "provider %s 引用了未知的 style_profile %r，已忽略该 profile（可用：%s）",
                provider_id, profile_name, available,
            )
        else:
            shared = style_profiles[profile_name].strip()
            style_text = shared + ("\n" + style_text if style_text else "")

    raw_aliases = expand_env_value(as_dict(entry.get("aliases")))
    models = [str(item).strip() for item in entry.get("models", []) if str(item).strip()]
    aliases: dict[str, str] = {}
    for raw_k, raw_v in raw_aliases.items():
        k = str(raw_k).strip()
        v = str(raw_v).strip()
        if not k or not v:
            continue
        if v not in models:
            logger.warning("provider %s 的 alias %r 指向不存在的模型 %r，已跳过", provider_id, k, v)
            continue
        aliases[k] = v

    return ProviderConfig(
        id=provider_id,
        protocol=str(entry.get("protocol", "")).strip().lower(),
        base_url=str(entry.get("base_url", "")).strip(),
        api_key_env=str(entry.get("api_key_env", "")).strip(),
        default_model=str(entry.get("default_model", "")).strip(),
        models=models,
        enabled=as_bool(entry.get("enabled", True), default=True),
        non_vision_models=[str(item).strip() for item in entry.get("non_vision_models", []) if str(item).strip()],
        timeout_seconds=float(entry.get("timeout_seconds", 45)),
        temperature=float(entry.get("temperature", 0.8)),
        max_output_tokens=int(entry.get("max_output_tokens", 800)),
        style_overrides=style_text,
        stream_enabled=as_bool(entry.get("stream_enabled", True), default=True),
        headers={str(k): str(v) for k, v in raw_headers.items()},
        user_agent=str(entry.get("user_agent", "")).strip(),
        extra_body=expand_env_value(as_dict(entry.get("extra_body"))),
        aliases=aliases,
        fallback_urls=[str(item).strip() for item in entry.get("fallback_urls", []) if str(item).strip()],
        proxy=str(entry.get("proxy", "")).strip(),
        prompt_caching=as_bool(entry.get("prompt_caching"), default=False),
        cache_ttl=str(entry.get("cache_ttl", "")).strip(),
        auth_method=str(entry.get("auth_method", "api_key")).strip().lower() or "api_key",
        builtin_search=as_bool(entry.get("builtin_search"), default=False),
    )


_MCP_NEGOTIATION_MODES = {"legacy", "auto", "modern"}


def _parse_enabled_mode(raw: Any) -> str:
    """解析 [tools] enabled_mode；非法取值回退 append 并告警。"""
    mode = str(raw if raw is not None else "append").strip().lower()
    if mode not in ("append", "replace"):
        if raw is not None:
            logger.warning("[tools] enabled_mode 非法取值 %r，回退为 append", raw)
        return "append"
    return mode


def _read_mcp_servers(raw_servers: list[dict[str, Any]]) -> list[MCPServerConfig]:
    servers: list[MCPServerConfig] = []
    seen_ids: set[str] = set()
    for entry in raw_servers:
        entry = expand_env_value(entry)
        server_id = str(entry.get("id", "")).strip()
        if not server_id:
            continue

        if server_id in seen_ids:
            logger.warning("跳过重复的 MCP server id：%s", server_id)
            continue
        seen_ids.add(server_id)

        negotiation = str(entry.get("negotiation", "legacy")).strip().lower() or "legacy"
        if negotiation not in _MCP_NEGOTIATION_MODES:
            logger.warning(
                "跳过 MCP server %s：未知 negotiation 模式 %r（仅支持 legacy/auto/modern）",
                server_id, negotiation,
            )
            continue

        transport = str(entry.get("transport", "stdio")).strip().lower() or "stdio"
        supported_versions = [
            str(v).strip()
            for v in entry.get("supported_protocol_versions", [])
            if str(v).strip()
        ]

        if negotiation in {"auto", "modern"}:
            if transport != "http":
                logger.warning(
                    "跳过 MCP server %s：%r 协商模式仅支持 HTTP transport（当前 %r）",
                    server_id, negotiation, transport,
                )
                continue
            if not supported_versions:
                logger.warning(
                    "跳过 MCP server %s：%r 协商模式需要 supported_protocol_versions",
                    server_id, negotiation,
                )
                continue

        raw_env = as_dict(entry.get("env"))
        raw_headers = as_dict(entry.get("headers"))
        servers.append(
            MCPServerConfig(
                id=server_id,
                transport=transport,
                enabled=as_bool(entry.get("enabled", True), default=True),
                timeout_seconds=float(entry.get("timeout_seconds", 30)),
                protocol_version=str(entry.get("protocol_version", "2025-03-26")).strip()
                or "2025-03-26",
                tool_prefix=str(entry.get("tool_prefix", "")).strip() or None,
                include_tools=[
                    str(item).strip()
                    for item in entry.get("include_tools", [])
                    if str(item).strip()
                ],
                exclude_tools=[
                    str(item).strip()
                    for item in entry.get("exclude_tools", [])
                    if str(item).strip()
                ],
                allowed_tools=[
                    str(item).strip()
                    for item in entry.get("allowed_tools", [])
                    if str(item).strip()
                ],
                command=str(entry.get("command", "")).strip(),
                args=[str(item) for item in entry.get("args", []) if str(item).strip()],
                cwd=str(entry.get("cwd", "")).strip() or None,
                env={str(k): str(v) for k, v in raw_env.items()},
                url=str(entry.get("url", "")).strip(),
                headers={str(k): str(v) for k, v in raw_headers.items()},
                image=str(entry.get("image", "")).strip(),
                docker_command=str(entry.get("docker_command", "docker")).strip() or "docker",
                docker_args=[str(item) for item in entry.get("docker_args", []) if str(item).strip()],
                mounts=[str(item).strip() for item in entry.get("mounts", []) if str(item).strip()],
                network=str(entry.get("network", "")).strip() or None,
                container_workdir=str(entry.get("container_workdir", "")).strip() or None,
                negotiation=negotiation,
                supported_protocol_versions=supported_versions,
            )
        )
    return servers


def load_personas_only(config_path: str | Path) -> dict[str, PersonaConfig]:
    """Parse only the persona section of llm.toml plus ``config/personas/`` directory.

    Used by hot-reload paths that must not touch providers/MCP/runtime; returns
    an empty dict if the config file is missing or defines no personas.
    """
    path = Path(config_path)
    if not path.exists():
        return {}

    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
    except tomllib.TOMLDecodeError as exc:
        logger.warning("load_personas_only 跳过损坏的 TOML：%s", exc)
        return {}

    personas_path = path.parent / "personas"
    raw_personas = data.get("personas", [])
    if not isinstance(raw_personas, list):
        raw_personas = []
    if personas_path.is_dir():
        raw_personas = raw_personas + _load_personas_from_dir(personas_path)
    return _read_personas(raw_personas)


def _read_providers_safe(raw_providers: Any, style_profiles: dict[str, str]) -> dict[str, ProviderConfig]:
    try:
        return _read_providers(
            raw_providers if isinstance(raw_providers, list) else [],
            style_profiles=style_profiles,
        )
    except Exception:
        logger.exception("provider 解析阶段发生未预期异常")
        return {}


def load_llm_config(path: str | Path) -> LLMConfig:
    config_path = Path(path)
    if not config_path.exists():
        return LLMConfig(load_error=f"未找到配置文件：{config_path}", source_path=config_path)

    try:
        with config_path.open("rb") as file:
            data = tomllib.load(file)
    except tomllib.TOMLDecodeError as exc:
        logger.exception("llm.toml 语法错误")
        return LLMConfig(load_error=f"TOML 语法错误：{exc}", source_path=config_path)

    personas = load_personas_only(config_path)

    runtime_raw = expand_env_value(as_dict(data.get("runtime")))
    triggers_raw = expand_env_value(as_dict(data.get("triggers")))
    tools_raw = expand_env_value(as_dict(data.get("tools")))
    mcp_raw = expand_env_value(as_dict(data.get("mcp")))
    daily_summary_raw = expand_env_value(as_dict(data.get("daily_summary")))
    daily_briefing_raw = expand_env_value(as_dict(data.get("daily_briefing")))
    weekly_report_raw = expand_env_value(as_dict(data.get("weekly_report")))
    monthly_report_raw = expand_env_value(as_dict(data.get("monthly_report")))
    image_preprocessing_raw = expand_env_value(as_dict(data.get("image_preprocessing")))
    raw_style_profiles = expand_env_value(as_dict(data.get("style_profiles")))
    style_profiles = {str(k).strip(): str(v).strip() for k, v in raw_style_profiles.items() if str(k).strip() and str(v).strip()}
    raw_pricing = as_dict(data.get("pricing"))
    raw_providers = data.get("providers", [])
    raw_mcp_servers = mcp_raw.get("servers", [])
    auto_search_raw = expand_env_value(as_dict(triggers_raw.get("auto_search")))
    quick_judge_raw = expand_env_value(as_dict(triggers_raw.get("quick_judge")))

    _enabled_tools = [
        str(item).strip()
        for item in tools_raw.get("enabled", [])
        if str(item).strip()
    ]
    _enabled_mode = _parse_enabled_mode(tools_raw.get("enabled_mode"))
    if _enabled_tools and "enabled_mode" not in tools_raw:
        # v1.11 及更早 enabled 非空 = 精确白名单；未显式声明 mode 的升级部署提示语义变化
        logger.warning(
            "[tools] enabled 非空且未设置 enabled_mode，按 append 语义在默认白名单与 MCP 工具之上追加；"
            '如需精确白名单请显式设置 enabled_mode = "replace"'
        )

    config = LLMConfig(
        runtime=RuntimeConfig(
            enabled=as_bool(runtime_raw.get("enabled", False), default=False),
            memory_enabled=as_bool(runtime_raw.get("memory_enabled", True), default=True),
            default_provider=str(runtime_raw.get("default_provider", "")).strip() or None,
            default_persona=str(runtime_raw.get("default_persona", "")).strip() or None,
            history_limit=int(runtime_raw.get("history_limit", 10)),
            history_max_messages_per_group=int(runtime_raw.get("history_max_messages_per_group", 40)),
            memory_limit=int(runtime_raw.get("memory_limit", 6)),
            memory_max_items_per_group=int(runtime_raw.get("memory_max_items_per_group", 200)),
            max_prompt_chars=int(runtime_raw.get("max_prompt_chars", 4000)),
            tool_calling_enabled=as_bool(runtime_raw.get("tool_calling_enabled", False), default=False),
            tool_max_rounds=int(runtime_raw.get("tool_max_rounds", 8)),
            tool_max_calls_per_round=int(runtime_raw.get("tool_max_calls_per_round", 16)),
            retry_max_attempts=int(runtime_raw.get("retry_max_attempts", 3)),
            retry_base_delay=float(runtime_raw.get("retry_base_delay", 1.0)),
            auto_memory_enabled=as_bool(runtime_raw.get("auto_memory_enabled", False), default=False),
            auto_memory_prompt=str(runtime_raw.get("auto_memory_prompt", "")).strip(),
            auto_memory_max_tokens=max(32, int(runtime_raw.get("auto_memory_max_tokens", 256))),
        ),
        triggers=TriggerConfig(
            default_prefix=str(triggers_raw.get("default_prefix", "/ai")).strip() or "/ai",
            allow_prefix=as_bool(triggers_raw.get("allow_prefix", True), default=True),
            allow_at=as_bool(triggers_raw.get("allow_at", True), default=True),
            empty_prompt_reply=str(
                triggers_raw.get("empty_prompt_reply", "请在触发指令或艾特后面补上想说的话。")
            ).strip()
            or "请在触发指令或艾特后面补上想说的话。",
        ),
        auto_search=AutoSearchConfig(
            enabled=as_bool(auto_search_raw.get("enabled", False), default=False),
            search_max_calls_per_round=max(1, min(int(auto_search_raw.get("search_max_calls_per_round", 3)), 32)),
        ),
        quick_judge=QuickJudgeConfig(
            provider_id=str(quick_judge_raw.get("provider_id", "")).strip(),
            model=str(quick_judge_raw.get("model", "")).strip(),
            timeout=max(0.5, float(quick_judge_raw.get("timeout", 2.0))),
            max_tokens=max(8, int(quick_judge_raw.get("max_tokens", 64))),
        ),
        tools=ToolsConfig(
            enabled=_enabled_tools,
            enabled_mode=_enabled_mode,
            discovery_mode=str(tools_raw.get("discovery_mode", "auto")).strip().lower() or "auto",
            discovery_min_tools=max(1, int(tools_raw.get("discovery_min_tools", 10))),
            discovery_search_limit=max(1, min(int(tools_raw.get("discovery_search_limit", 5)), 20)),
            discovery_max_loaded_tools=max(1, min(int(tools_raw.get("discovery_max_loaded_tools", 12)), 64)),
            always_loaded=[
                str(item).strip()
                for item in tools_raw.get("always_loaded", [])
                if str(item).strip()
            ],
        ),
        mcp=MCPConfig(
            enabled=as_bool(mcp_raw.get("enabled", False), default=False),
            servers=_read_mcp_servers(raw_mcp_servers if isinstance(raw_mcp_servers, list) else []),
        ),
        providers=_read_providers_safe(raw_providers, style_profiles),
        personas=personas,
        daily_summary=DailySummaryConfig(
            enabled=as_bool(daily_summary_raw.get("enabled", False), default=False),
            generate_cron=str(daily_summary_raw.get("generate_cron", "0 6 * * *")).strip() or "0 6 * * *",
            publish_cron=str(daily_summary_raw.get("publish_cron", "0 12 * * *")).strip() or "0 12 * * *",
            min_messages=max(1, int(daily_summary_raw.get("min_messages", 30))),
            summary_length_hint=max(100, int(daily_summary_raw.get("summary_length_hint", 2000))),
            model_cascade=[
                str(item).strip()
                for item in daily_summary_raw.get("model_cascade", [])
                if str(item).strip()
            ],
        ),
        daily_briefing=DailyBriefingConfig(
            enabled=as_bool(daily_briefing_raw.get("enabled", False), default=False),
            morning_cron=str(daily_briefing_raw.get("morning_cron", "0 8 * * *")).strip() or "0 8 * * *",
            noon_cron=str(daily_briefing_raw.get("noon_cron", "0 12 * * *")).strip() or "0 12 * * *",
            evening_cron=str(daily_briefing_raw.get("evening_cron", "0 22 * * *")).strip() or "0 22 * * *",
            min_messages_for_llm=max(1, int(daily_briefing_raw.get("min_messages_for_llm", 5))),
            active_users_limit=max(1, int(daily_briefing_raw.get("active_users_limit", 5))),
            hot_words_limit=max(1, int(daily_briefing_raw.get("hot_words_limit", 5))),
            sample_messages_limit=max(1, int(daily_briefing_raw.get("sample_messages_limit", 60))),
            max_context_chars=max(1000, int(daily_briefing_raw.get("max_context_chars", 40000))),
            max_output_chars=max(80, int(daily_briefing_raw.get("max_output_chars", 320))),
            model_cascade=[
                str(item).strip()
                for item in daily_briefing_raw.get("model_cascade", [])
                if str(item).strip()
            ],
        ),
        weekly_report=WeeklyReportConfig(
            enabled=as_bool(weekly_report_raw.get("enabled", False), default=False),
            generate_cron=str(weekly_report_raw.get("generate_cron", "0 9 * * 1")).strip() or "0 9 * * 1",
            publish_cron=str(weekly_report_raw.get("publish_cron", "0 10 * * *")).strip() or "0 10 * * *",
            min_messages=max(1, int(weekly_report_raw.get("min_messages", 100))),
            length_hint=max(200, int(weekly_report_raw.get("length_hint", 2000))),
            sample_per_day=max(1, int(weekly_report_raw.get("sample_per_day", 50))),
            model_cascade=[
                str(item).strip()
                for item in weekly_report_raw.get("model_cascade", [])
                if str(item).strip()
            ],
        ),
        monthly_report=MonthlyReportConfig(
            enabled=as_bool(monthly_report_raw.get("enabled", False), default=False),
            generate_cron=str(monthly_report_raw.get("generate_cron", "0 9 1 * *")).strip() or "0 9 1 * *",
            publish_cron=str(monthly_report_raw.get("publish_cron", "0 10 * * *")).strip() or "0 10 * * *",
            min_messages=max(1, int(monthly_report_raw.get("min_messages", 300))),
            length_hint=max(200, int(monthly_report_raw.get("length_hint", 2500))),
            sample_per_day=max(1, int(monthly_report_raw.get("sample_per_day", 20))),
            model_cascade=[
                str(item).strip()
                for item in monthly_report_raw.get("model_cascade", [])
                if str(item).strip()
            ],
        ),
        image_preprocessing=ImagePreprocessingConfig(
            enabled=as_bool(image_preprocessing_raw.get("enabled", False), default=False),
            provider_id=str(image_preprocessing_raw.get("provider_id", "")).strip(),
            model=str(image_preprocessing_raw.get("model", "")).strip(),
            max_tokens=max(
                80,
                min(
                    int(image_preprocessing_raw.get("max_tokens", 300)),
                    MAX_IMAGE_PREPROCESSING_TOKENS,
                ),
            ),
            temperature=float(image_preprocessing_raw.get("temperature", 0.3)),
            prompt=str(image_preprocessing_raw.get("prompt", "")).strip(),
        ),
        style_profiles=style_profiles,
        pricing=_read_pricing(raw_pricing),
        source_path=config_path,
    )

    try:
        _validate_and_fix_config(config)
    except Exception:
        logger.exception("配置校验阶段异常")
        config.load_error = "配置校验时发生内部错误"
    return config


def _validate_and_fix_config(config: LLMConfig) -> None:
    """Validate cross-references and fix salvageable issues.

    Single-provider problems result in that provider being skipped (logged);
    only truly fatal issues (no providers at all, no personas at all) set
    ``load_error``.  This ensures one bad provider config never blocks others.

    Two observability principles: a fallback after the *explicitly configured*
    default provider is pruned is recorded in ``load_error`` (fail-visible,
    same as an unknown default_provider; auto-selected defaults re-fall-back
    silently), and disabled features' model_cascades are not validated at all.
    """
    errors: list[str] = []

    if not config.providers:
        config.load_error = "LLM 配置中没有可用的 providers"
        return

    # -- default_provider fallback --
    # 用户在配置里显式写的默认 provider（可能为 None）：剪除后回退只有对显式值
    # 才记 load_error；自动选择的再回退保持静默（维持"尽力可用"语义）。
    explicit_default_provider = config.runtime.default_provider
    if config.runtime.default_provider is None:
        config.runtime.default_provider = next(iter(config.providers))
    elif config.runtime.default_provider not in config.providers:
        errors.append(f"默认 provider {config.runtime.default_provider!r} 不存在，已回退")
        config.runtime.default_provider = next(iter(config.providers))

    # -- personas --
    if not config.personas:
        config.load_error = "LLM 配置中没有可用的人格"
        return
    if config.runtime.default_persona is None:
        config.runtime.default_persona = next(iter(config.personas))
    elif config.runtime.default_persona not in config.personas:
        fallback = next(iter(config.personas))
        errors.append(f"默认 persona {config.runtime.default_persona!r} 不存在，已回退为 {fallback!r}")
        config.runtime.default_persona = fallback

    # -- tools --
    if config.tools.discovery_mode not in {"off", "on", "auto"}:
        config.tools.discovery_mode = "auto"

    # -- per-provider validation: collect and prune --
    bad_providers: list[str] = []
    for pid, provider in config.providers.items():
        provider_errors: list[str] = []
        if provider.protocol not in {"openai", "claude", "gemini"}:
            provider_errors.append(f"未知协议 {provider.protocol!r}")
        if provider.auth_method not in {"api_key", "bearer"}:
            provider_errors.append(f"未知 auth_method {provider.auth_method!r}（仅支持 api_key / bearer）")
        if provider.protocol == "claude" and provider.cache_ttl not in ("", "5m", "1h"):
            provider_errors.append(f"非法 cache_ttl {provider.cache_ttl!r}（claude 仅支持 5m / 1h，留空=默认 5min）")
        if provider.builtin_search and provider.protocol != "gemini":
            # 非 gemini 协议不剪除 provider：键误配只影响该键本身，记录
            # warning 即可，请求级生效由 provider_builtin_search_active 兜底为惰性。
            logger.warning(
                "provider %s 的 builtin_search 仅支持 gemini 协议，当前协议 %r 下该配置不生效",
                pid,
                provider.protocol,
            )
        if not provider.base_url:
            provider_errors.append("缺少 base_url")
        if not provider.api_key_env:
            provider_errors.append("缺少 api_key_env")
        if not provider.default_model:
            provider_errors.append("缺少 default_model")
        if provider.default_model and provider.default_model not in provider.models:
            provider.models.insert(0, provider.default_model)
            logger.warning("provider %s 的 default_model %r 不在 models 列表中，已自动添加", pid, provider.default_model)

        if provider_errors:
            logger.error("provider %s 配置无效：%s，已跳过", pid, "; ".join(provider_errors))
            bad_providers.append(pid)

    for pid in bad_providers:
        del config.providers[pid]

    # Re-validate default_provider in case it was among the deleted ones.
    if config.runtime.default_provider not in config.providers:
        if config.providers:
            fallback = next(iter(config.providers))
            # Fail-visible，与上方 default_provider 指向不存在 id 的语义一致：
            # 静默换用与配置不符的 provider 比显式拒绝更糟。全部剪除时不重复记录
            # （下方聚合错误已覆盖）；自动选择的再回退不记录。
            if (
                explicit_default_provider is not None
                and config.runtime.default_provider == explicit_default_provider
            ):
                errors.append(
                    f"默认 provider {explicit_default_provider!r} 已被剪除，已回退为 {fallback!r}"
                )
            config.runtime.default_provider = fallback
        else:
            config.runtime.default_provider = None

    if bad_providers and not config.providers:
        errors.append(f"全部 {len(bad_providers)} 个 provider 均被跳过：{', '.join(bad_providers)}")

    # -- cross-reference validation (non-fatal, augments errors) --
    if config.image_preprocessing.enabled and config.image_preprocessing.provider_id:
        if config.image_preprocessing.provider_id not in config.providers:
            errors.append(
                f"image_preprocessing.provider_id {config.image_preprocessing.provider_id!r} 不存在"
            )

    for cascade_name, feature_enabled, cascade_list in [
        ("daily_summary.model_cascade", config.daily_summary.enabled, config.daily_summary.model_cascade),
        ("daily_briefing.model_cascade", config.daily_briefing.enabled, config.daily_briefing.model_cascade),
        ("weekly_report.model_cascade", config.weekly_report.enabled, config.weekly_report.model_cascade),
        ("monthly_report.model_cascade", config.monthly_report.enabled, config.monthly_report.model_cascade),
    ]:
        if not feature_enabled:
            continue
        for entry in cascade_list:
            provider_id = entry.split("/", 1)[0].strip()
            if provider_id == "@default":
                continue
            if provider_id not in config.providers:
                errors.append(f"{cascade_name} 引用了不存在的 provider {provider_id!r}")

    if errors:
        config.load_error = "; ".join(errors)
        logger.warning("LLM 配置存在问题：%s", config.load_error)
