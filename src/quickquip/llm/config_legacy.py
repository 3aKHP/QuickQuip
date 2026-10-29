"""Frozen 1.16.1 TOML parser used by migration and compatibility tests."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
import tomllib

from quickquip.common.config_utils import as_bool, as_dict, expand_env_value as _expand_env_value
from contextvars import ContextVar
from quickquip.llm.skills import MAX_SCRIPT_TIMEOUT_MS
from quickquip.llm.config import (
    TriggerConfig,
    AutoSearchConfig,
    QuickJudgeConfig,
    RuntimeConfig,
    ToolsConfig,
    SkillsConfig,
    MCPServerConfig,
    MCPConfig,
    PersonaConfig,
    ImagePreprocessingConfig,
    ProviderConfig,
    PricingRates,
    DailySummaryConfig,
    DailyBriefingConfig,
    WeeklyReportConfig,
    MonthlyReportConfig,
    LLMConfig,
    MAX_IMAGE_PREPROCESSING_TOKENS,
    DEFAULT_RETRY_MAX_ATTEMPTS,
    DEFAULT_RETRY_BASE_DELAY,
    DEFAULT_RETRY_JITTER,
    AGENT_REPLAY_LOOP_TOKENS_FLOOR,
    AGENT_REPLAY_LOOP_TOKENS_CEILING,
    DEFAULT_MAX_INLINE_MEDIA_BYTES,
    RESPONSES_PROFILE_IDS,
    REASONING_EFFORT_CHOICES,
    DEFAULT_RESPONSES_PROFILE_ID,
)

logger = logging.getLogger(__name__)

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
        parsed_scope = [
            s for s in (str(s).strip().lower() for s in raw_scope) if s in {"group", "private"}
        ]
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
                entry["system_prompt"] = (
                    (existing + "\n\n" + shared_system).lstrip() if existing else shared_system
                )
            if shared_style:
                existing = str(entry.get("style_prompt", "")).rstrip()
                entry["style_prompt"] = (
                    (existing + "\n\n" + shared_style).lstrip() if existing else shared_style
                )
            personas.append(entry)
        elif "personas" in data:
            for entry in data["personas"]:
                entry = dict(entry)
                if shared_system:
                    existing = str(entry.get("system_prompt", "")).rstrip()
                    entry["system_prompt"] = (
                        (existing + "\n\n" + shared_system).lstrip() if existing else shared_system
                    )
                if shared_style:
                    existing = str(entry.get("style_prompt", "")).rstrip()
                    entry["style_prompt"] = (
                        (existing + "\n\n" + shared_style).lstrip() if existing else shared_style
                    )
                personas.append(entry)

    return personas


def _read_providers(
    raw_providers: list[dict[str, Any]],
    *,
    style_profiles: dict[str, str] | None = None,
) -> dict[str, ProviderConfig]:
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
                provider_id,
                profile_name,
                available,
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
        non_vision_models=[
            str(item).strip() for item in entry.get("non_vision_models", []) if str(item).strip()
        ],
        timeout_seconds=float(entry.get("timeout_seconds", 45)),
        temperature=float(entry.get("temperature", 0.8)),
        max_output_tokens=int(entry.get("max_output_tokens", 800)),
        style_overrides=style_text,
        stream_enabled=as_bool(entry.get("stream_enabled", True), default=True),
        headers={str(k): str(v) for k, v in raw_headers.items()},
        user_agent=str(entry.get("user_agent", "")).strip(),
        extra_body=expand_env_value(as_dict(entry.get("extra_body"))),
        aliases=aliases,
        fallback_urls=[
            str(item).strip() for item in entry.get("fallback_urls", []) if str(item).strip()
        ],
        proxy=str(entry.get("proxy", "")).strip(),
        prompt_caching=as_bool(entry.get("prompt_caching"), default=False),
        cache_ttl=str(entry.get("cache_ttl", "")).strip(),
        auth_method=str(entry.get("auth_method", "api_key")).strip().lower() or "api_key",
        builtin_search=as_bool(entry.get("builtin_search"), default=False),
        responses_profile=(
            str(entry.get("responses_profile", DEFAULT_RESPONSES_PROFILE_ID)).strip().lower()
            or DEFAULT_RESPONSES_PROFILE_ID
        ),
        reasoning_effort=str(entry.get("reasoning_effort", "")).strip().lower(),
        epoch_context_tokens=_as_optional_int(entry.get("epoch_context_tokens")),
        epoch_cold_idle_seconds=_as_optional_int(entry.get("epoch_cold_idle_seconds")),
        epoch_cold_target_tokens=_as_optional_int(entry.get("epoch_cold_target_tokens")),
        epoch_cold_trigger_tokens=_as_optional_int(entry.get("epoch_cold_trigger_tokens")),
        epoch_hot_target_tokens=_as_optional_int(entry.get("epoch_hot_target_tokens")),
        epoch_cap_tokens=_as_optional_int(entry.get("epoch_cap_tokens")),
        request_input_token_budget=_nonpositive_as_none(entry.get("request_input_token_budget")),
        max_inline_media_bytes=max(
            0, int(entry.get("max_inline_media_bytes", DEFAULT_MAX_INLINE_MEDIA_BYTES))
        ),
        agent_replay_loop_tokens=_clamped_optional_int(
            entry.get("agent_replay_loop_tokens"),
            floor=AGENT_REPLAY_LOOP_TOKENS_FLOOR,
            ceiling=AGENT_REPLAY_LOOP_TOKENS_CEILING,
        ),
        model_context_windows={
            str(name): max(1024, int(size))
            for name, size in as_dict(entry.get("model_context_windows")).items()
        },
    )


def _as_optional_int(raw: Any) -> int | None:
    """provider 级可选整数键：缺省/空 = None（继承 runtime）。

    TOML 数直转（float 截断，与既有 ``int(entry.get(...))`` 范式一致）；字符串
    走 ``int()``；解析失败回退 None 并告警——键级笔误不得扩大为整 provider 剪除。
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    text = str(raw).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        logger.warning("epoch_* 覆盖值 %r 无法解析为整数，回退继承 [runtime]", raw)
        return None


def _clamped_optional_int(raw: Any, *, floor: int, ceiling: int) -> int | None:
    """provider 级可选整数键 + 范围钳制：缺省/不可解析回退 None，越界钳制到边界并告警。"""
    value = _as_optional_int(raw)
    if value is None:
        return None
    clamped = min(ceiling, max(floor, value))
    if clamped != value:
        logger.warning(
            "provider 覆盖值 %d 超出 [%d, %d]，已钳制为 %d", value, floor, ceiling, clamped
        )
    return clamped


def _nonpositive_as_none(raw: Any) -> int | None:
    """非正数视为未配置（继承推导/缺省）：0/负值不是合法预算，告警不致命。"""
    value = _as_optional_int(raw)
    if value is not None and value <= 0:
        logger.warning("provider 覆盖值 %d 非正数，按未配置处理（继承推导/缺省）", value)
        return None
    return value


_MCP_NEGOTIATION_MODES = {"legacy", "auto", "modern"}


def _parse_enabled_mode(raw: Any) -> str:
    """解析 [tools] enabled_mode；非法取值回退 append 并告警。"""
    mode = str(raw if raw is not None else "append").strip().lower()
    if mode not in ("append", "replace"):
        if raw is not None:
            logger.warning("[tools] enabled_mode 非法取值 %r，回退为 append", raw)
        return "append"
    return mode


def _skills_positive_int(raw: Any, *, default: int, label: str, maximum: int | None = None) -> int:
    """[skills] 正整数键：不可解析/非正数回退默认并告警；超过 maximum 钳制并告警。"""
    value: int
    if isinstance(raw, bool) or raw is None:
        value = default
        if raw is not None:
            logger.warning("[skills] %s 非法取值 %r，回退默认值 %d", label, raw, default)
    elif isinstance(raw, (int, float)):
        value = int(raw)
    else:
        try:
            value = int(str(raw).strip())
        except ValueError:
            logger.warning("[skills] %s 非法取值 %r，回退默认值 %d", label, raw, default)
            return default
    if value <= 0:
        logger.warning("[skills] %s 须为正整数（当前 %r），回退默认值 %d", label, raw, default)
        return default
    if maximum is not None and value > maximum:
        logger.warning("[skills] %s=%d 超过上限 %d，已钳制", label, value, maximum)
        return maximum
    return value


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
                server_id,
                negotiation,
            )
            continue

        transport = str(entry.get("transport", "stdio")).strip().lower() or "stdio"
        supported_versions = [
            str(v).strip() for v in entry.get("supported_protocol_versions", []) if str(v).strip()
        ]

        if negotiation in {"auto", "modern"}:
            if transport != "http":
                logger.warning(
                    "跳过 MCP server %s：%r 协商模式仅支持 HTTP transport（当前 %r）",
                    server_id,
                    negotiation,
                    transport,
                )
                continue
            if not supported_versions:
                logger.warning(
                    "跳过 MCP server %s：%r 协商模式需要 supported_protocol_versions",
                    server_id,
                    negotiation,
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
                docker_args=[
                    str(item) for item in entry.get("docker_args", []) if str(item).strip()
                ],
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


def _read_providers_safe(
    raw_providers: Any, style_profiles: dict[str, str]
) -> dict[str, ProviderConfig]:
    try:
        return _read_providers(
            raw_providers if isinstance(raw_providers, list) else [],
            style_profiles=style_profiles,
        )
    except Exception:
        logger.exception("provider 解析阶段发生未预期异常")
        return {}


def _load_llm_config(path: str | Path) -> LLMConfig:
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
    # 【现场】补丁两键防护：非法取值静默通过会让 budget=0 的「关停」意图
    # 实际仍服役最新 1 条且无告警——与相邻 epoch_* 键的回退范式对齐
    recent_context_token_budget = int(runtime_raw.get("recent_context_token_budget", 800))
    if recent_context_token_budget <= 0:
        logger.warning(
            "[runtime] recent_context_token_budget=%d 非法（须 > 0），回退默认值 800",
            recent_context_token_budget,
        )
        recent_context_token_budget = 800
    recent_context_floor_seconds = int(runtime_raw.get("recent_context_floor_seconds", 300))
    if recent_context_floor_seconds < 0:
        logger.warning(
            "[runtime] recent_context_floor_seconds=%d 非法（须 >= 0），回退默认值 300",
            recent_context_floor_seconds,
        )
        recent_context_floor_seconds = 300
    triggers_raw = expand_env_value(as_dict(data.get("triggers")))
    tools_raw = expand_env_value(as_dict(data.get("tools")))
    skills_raw = expand_env_value(as_dict(data.get("skills")))
    mcp_raw = expand_env_value(as_dict(data.get("mcp")))
    daily_summary_raw = expand_env_value(as_dict(data.get("daily_summary")))
    daily_briefing_raw = expand_env_value(as_dict(data.get("daily_briefing")))
    weekly_report_raw = expand_env_value(as_dict(data.get("weekly_report")))
    monthly_report_raw = expand_env_value(as_dict(data.get("monthly_report")))
    image_preprocessing_raw = expand_env_value(as_dict(data.get("image_preprocessing")))
    raw_style_profiles = expand_env_value(as_dict(data.get("style_profiles")))
    # 空内容家族是合法占位（引用方无风格附加块），只过滤空键——家族内容
    # 待调研定版期间以空串声明，避免被误判为未知引用。
    style_profiles = {
        str(k).strip(): str(v).strip() for k, v in raw_style_profiles.items() if str(k).strip()
    }
    raw_pricing = as_dict(data.get("pricing"))
    raw_providers = data.get("providers", [])
    raw_mcp_servers = mcp_raw.get("servers", [])
    auto_search_raw = expand_env_value(as_dict(triggers_raw.get("auto_search")))
    quick_judge_raw = expand_env_value(as_dict(triggers_raw.get("quick_judge")))

    _enabled_tools = [
        str(item).strip() for item in tools_raw.get("enabled", []) if str(item).strip()
    ]
    _enabled_mode = _parse_enabled_mode(tools_raw.get("enabled_mode"))
    if _enabled_tools and "enabled_mode" not in tools_raw:
        # v1.11 及更早 enabled 非空 = 精确白名单；未显式声明 mode 的升级部署提示语义变化
        logger.warning(
            "[tools] enabled 非空且未设置 enabled_mode，"
            "按 append 语义在默认白名单与 MCP 工具之上追加；"
            '如需精确白名单请显式设置 enabled_mode = "replace"'
        )

    if int(runtime_raw.get("reply_split_threshold_chars", 800)) > int(
        runtime_raw.get("reply_chunk_max_chars", 1200)
    ):
        return LLMConfig(
            load_error="reply_split_threshold_chars 不能超过 reply_chunk_max_chars",
            source_path=config_path,
        )
    legacy_agent_delivery = runtime_raw.get("agent_delivery_enabled")
    legacy_fallback_active = legacy_agent_delivery is not None and (
        "agent_delivery_intermediate_enabled" not in runtime_raw
        or "agent_delivery_final_enabled" not in runtime_raw
    )
    if legacy_fallback_active:
        logger.warning(
            "[runtime] agent_delivery_enabled 已废弃：存在未显式配置的交付域，"
            "该域正按旧键值映射，请迁移到 agent_delivery_intermediate_enabled / "
            "agent_delivery_final_enabled"
        )
    elif legacy_agent_delivery is not None:
        logger.debug("[runtime] agent_delivery_enabled 已被两枚新键取代，忽略旧键")
    config = LLMConfig(
        runtime=RuntimeConfig(
            claude_code_device_id=str(runtime_raw.get("claude_code_device_id", "")).strip(),
            enabled=as_bool(runtime_raw.get("enabled", False), default=False),
            memory_enabled=as_bool(runtime_raw.get("memory_enabled", True), default=True),
            default_provider=str(runtime_raw.get("default_provider", "")).strip() or None,
            default_persona=str(runtime_raw.get("default_persona", "")).strip() or None,
            history_limit=int(runtime_raw.get("history_limit", 10)),
            history_max_messages_per_group=int(
                runtime_raw.get("history_max_messages_per_group", 40)
            ),
            memory_limit=int(runtime_raw.get("memory_limit", 5)),
            memory_max_items_per_group=int(runtime_raw.get("memory_max_items_per_group", 1000)),
            max_prompt_chars=int(runtime_raw.get("max_prompt_chars", 4000)),
            tool_calling_enabled=as_bool(
                runtime_raw.get("tool_calling_enabled", False), default=False
            ),
            tool_max_rounds=int(runtime_raw.get("tool_max_rounds", 8)),
            tool_max_calls_per_round=int(runtime_raw.get("tool_max_calls_per_round", 16)),
            retry_max_attempts=int(
                runtime_raw.get("retry_max_attempts", DEFAULT_RETRY_MAX_ATTEMPTS)
            ),
            retry_base_delay=float(runtime_raw.get("retry_base_delay", DEFAULT_RETRY_BASE_DELAY)),
            retry_jitter=min(
                1.0, max(0.0, float(runtime_raw.get("retry_jitter", DEFAULT_RETRY_JITTER)))
            ),
            auto_memory_enabled=as_bool(
                runtime_raw.get("auto_memory_enabled", False), default=False
            ),
            auto_memory_prompt=str(runtime_raw.get("auto_memory_prompt", "")).strip(),
            auto_memory_max_tokens=max(32, int(runtime_raw.get("auto_memory_max_tokens", 256))),
            epoch_context_tokens=int(runtime_raw.get("epoch_context_tokens", 8000)),
            epoch_cold_idle_seconds=int(runtime_raw.get("epoch_cold_idle_seconds", 300)),
            epoch_cold_target_tokens=int(runtime_raw.get("epoch_cold_target_tokens", 4000)),
            epoch_cold_trigger_tokens=int(runtime_raw.get("epoch_cold_trigger_tokens", 5000)),
            epoch_hot_target_tokens=int(runtime_raw.get("epoch_hot_target_tokens", 32000)),
            epoch_cap_tokens=int(runtime_raw.get("epoch_cap_tokens", 64000)),
            request_input_token_budget=max(
                1024, int(runtime_raw.get("request_input_token_budget", 96_000))
            ),
            agent_record_retention_days=max(
                1, int(runtime_raw.get("agent_record_retention_days", 30))
            ),
            agent_record_max_loops_per_scope=max(
                1, int(runtime_raw.get("agent_record_max_loops_per_scope", 1000))
            ),
            agent_record_max_bytes_per_scope=max(
                1024, int(runtime_raw.get("agent_record_max_bytes_per_scope", 67_108_864))
            ),
            agent_delivery_intermediate_enabled=as_bool(
                runtime_raw.get("agent_delivery_intermediate_enabled"),
                default=as_bool(legacy_agent_delivery, default=False),
            ),
            agent_delivery_final_enabled=as_bool(
                runtime_raw.get("agent_delivery_final_enabled"),
                default=as_bool(legacy_agent_delivery, default=False),
            ),
            agent_replay_loop_tokens=min(
                AGENT_REPLAY_LOOP_TOKENS_CEILING,
                max(
                    AGENT_REPLAY_LOOP_TOKENS_FLOOR,
                    int(runtime_raw.get("agent_replay_loop_tokens", 4096)),
                ),
            ),
            reply_split_threshold_chars=max(
                1, int(runtime_raw.get("reply_split_threshold_chars", 800))
            ),
            reply_chunk_max_chars=max(1, int(runtime_raw.get("reply_chunk_max_chars", 1200))),
            reply_send_interval_ms=min(
                10_000, max(0, int(runtime_raw.get("reply_send_interval_ms", 800)))
            ),
            reply_max_chunks_per_loop=min(
                256, max(1, int(runtime_raw.get("reply_max_chunks_per_loop", 64)))
            ),
            mention_cooldown_seconds=min(
                86_400.0,
                max(0.0, float(runtime_raw.get("mention_cooldown_seconds", 600.0))),
            ),
            recent_context_token_budget=recent_context_token_budget,
            recent_context_floor_seconds=recent_context_floor_seconds,
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
            search_max_calls_per_round=max(
                1, min(int(auto_search_raw.get("search_max_calls_per_round", 3)), 32)
            ),
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
            discovery_max_loaded_tools=max(
                1, min(int(tools_raw.get("discovery_max_loaded_tools", 12)), 64)
            ),
            always_loaded=[
                str(item).strip()
                for item in tools_raw.get("always_loaded", [])
                if str(item).strip()
            ],
        ),
        skills=SkillsConfig(
            enabled=as_bool(skills_raw.get("enabled", True), default=True),
            catalog_dir=str(skills_raw.get("catalog_dir", "")).strip(),
            catalog_max_bytes=_skills_positive_int(
                skills_raw.get("catalog_max_bytes"),
                default=8192,
                label="catalog_max_bytes",
            ),
            resource_max_bytes=_skills_positive_int(
                skills_raw.get("resource_max_bytes"),
                default=65536,
                label="resource_max_bytes",
            ),
            search_max_results=_skills_positive_int(
                skills_raw.get("search_max_results"),
                default=50,
                label="search_max_results",
            ),
            search_max_output_bytes=_skills_positive_int(
                skills_raw.get("search_max_output_bytes"),
                default=32768,
                label="search_max_output_bytes",
            ),
            script_timeout_ms=_skills_positive_int(
                skills_raw.get("script_timeout_ms"),
                default=30000,
                label="script_timeout_ms",
                maximum=MAX_SCRIPT_TIMEOUT_MS,
            ),
            script_max_output_bytes=_skills_positive_int(
                skills_raw.get("script_max_output_bytes"),
                default=65536,
                label="script_max_output_bytes",
            ),
        ),
        mcp=MCPConfig(
            enabled=as_bool(mcp_raw.get("enabled", False), default=False),
            servers=_read_mcp_servers(raw_mcp_servers if isinstance(raw_mcp_servers, list) else []),
        ),
        providers=_read_providers_safe(raw_providers, style_profiles),
        personas=personas,
        daily_summary=DailySummaryConfig(
            enabled=as_bool(daily_summary_raw.get("enabled", False), default=False),
            generate_cron=str(daily_summary_raw.get("generate_cron", "0 6 * * *")).strip()
            or "0 6 * * *",
            publish_cron=str(daily_summary_raw.get("publish_cron", "0 12 * * *")).strip()
            or "0 12 * * *",
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
            morning_cron=str(daily_briefing_raw.get("morning_cron", "0 8 * * *")).strip()
            or "0 8 * * *",
            noon_cron=str(daily_briefing_raw.get("noon_cron", "0 12 * * *")).strip()
            or "0 12 * * *",
            evening_cron=str(daily_briefing_raw.get("evening_cron", "0 22 * * *")).strip()
            or "0 22 * * *",
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
            generate_cron=str(weekly_report_raw.get("generate_cron", "0 9 * * 1")).strip()
            or "0 9 * * 1",
            publish_cron=str(weekly_report_raw.get("publish_cron", "0 10 * * *")).strip()
            or "0 10 * * *",
            min_messages=max(1, int(weekly_report_raw.get("min_messages", 100))),
            length_hint=max(200, int(weekly_report_raw.get("length_hint", 2000))),
            model_cascade=[
                str(item).strip()
                for item in weekly_report_raw.get("model_cascade", [])
                if str(item).strip()
            ],
        ),
        monthly_report=MonthlyReportConfig(
            enabled=as_bool(monthly_report_raw.get("enabled", False), default=False),
            generate_cron=str(monthly_report_raw.get("generate_cron", "0 9 1 * *")).strip()
            or "0 9 1 * *",
            publish_cron=str(monthly_report_raw.get("publish_cron", "0 10 * * *")).strip()
            or "0 10 * * *",
            min_messages=max(1, int(monthly_report_raw.get("min_messages", 300))),
            length_hint=max(200, int(monthly_report_raw.get("length_hint", 2500))),
            input_char_budget=max(8_000, int(monthly_report_raw.get("input_char_budget", 240_000))),
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

    # 上游重试策略盖章：[runtime] 段是唯一配置入口，统一注入各 provider，
    # 使所有 LLM 调用方经 build_provider_client 零改动继承全局重试参数。
    for provider in config.providers.values():
        provider.retry_max_attempts = config.runtime.retry_max_attempts
        provider.retry_base_delay = config.runtime.retry_base_delay
        provider.retry_jitter = config.runtime.retry_jitter

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
        errors.append(
            f"默认 persona {config.runtime.default_persona!r} 不存在，已回退为 {fallback!r}"
        )
        config.runtime.default_persona = fallback

    # -- tools --
    if config.tools.discovery_mode not in {"off", "on", "auto"}:
        config.tools.discovery_mode = "auto"

    # -- per-provider validation: collect and prune --
    bad_providers: list[str] = []
    for pid, provider in config.providers.items():
        provider_errors: list[str] = []
        if provider.protocol not in {"openai", "claude", "gemini", "openai_responses"}:
            provider_errors.append(f"未知协议 {provider.protocol!r}")
        # openai_responses 专属键的词表校验（模块级常量单源，供
        # provider/openai_responses 反向引用与守护测试对齐）。
        if provider.protocol == "openai_responses":
            if provider.responses_profile not in RESPONSES_PROFILE_IDS:
                provider_errors.append(
                    f"非法 responses_profile {provider.responses_profile!r}"
                    f"（可用：{' / '.join(sorted(RESPONSES_PROFILE_IDS))}）"
                )
        # 思考档位全协议校验（wire 翻译/钳制见 thinking.resolve_thinking）。
        if provider.reasoning_effort not in ("", *REASONING_EFFORT_CHOICES):
            provider_errors.append(
                f"非法 reasoning_effort {provider.reasoning_effort!r}"
                f"（可用：{'/'.join(REASONING_EFFORT_CHOICES)}，留空不发送）"
            )
        if provider.auth_method not in {"api_key", "bearer"}:
            provider_errors.append(
                f"未知 auth_method {provider.auth_method!r}（仅支持 api_key / bearer）"
            )
        if provider.protocol == "claude" and provider.cache_ttl not in ("", "5m", "1h"):
            provider_errors.append(
                f"非法 cache_ttl {provider.cache_ttl!r}（claude 仅支持 5m / 1h，留空=默认 5min）"
            )
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
            logger.warning(
                "provider %s 的 default_model %r 不在 models 列表中，已自动添加",
                pid,
                provider.default_model,
            )

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
        (
            "daily_summary.model_cascade",
            config.daily_summary.enabled,
            config.daily_summary.model_cascade,
        ),
        (
            "daily_briefing.model_cascade",
            config.daily_briefing.enabled,
            config.daily_briefing.model_cascade,
        ),
        (
            "weekly_report.model_cascade",
            config.weekly_report.enabled,
            config.weekly_report.model_cascade,
        ),
        (
            "monthly_report.model_cascade",
            config.monthly_report.enabled,
            config.monthly_report.model_cascade,
        ),
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


_PRESERVE_ENV = ContextVar("legacy_preserve_env", default=False)


def expand_env_value(value):
    return value if _PRESERVE_ENV.get() else _expand_env_value(value)


def load_llm_config(path: str | Path, *, preserve_env=False) -> LLMConfig:
    token = _PRESERVE_ENV.set(preserve_env)
    try:
        return _load_llm_config(path)
    finally:
        _PRESERVE_ENV.reset(token)
