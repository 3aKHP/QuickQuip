from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from typing import Any
import tomllib


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


@dataclass(slots=True)
class ProviderConfig:
    id: str
    protocol: str
    base_url: str
    api_key_env: str
    default_model: str
    models: list[str]
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
class LLMConfig:
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    triggers: TriggerConfig = field(default_factory=TriggerConfig)
    auto_search: AutoSearchConfig = field(default_factory=AutoSearchConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    personas: dict[str, PersonaConfig] = field(default_factory=dict)
    daily_summary: DailySummaryConfig = field(default_factory=DailySummaryConfig)
    daily_briefing: DailyBriefingConfig = field(default_factory=DailyBriefingConfig)
    image_preprocessing: ImagePreprocessingConfig = field(default_factory=ImagePreprocessingConfig)
    style_profiles: dict[str, str] = field(default_factory=dict)
    load_error: str | None = None
    source_path: Path | None = None

    @property
    def is_available(self) -> bool:
        return self.load_error is None and self.runtime.enabled and bool(self.providers)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand_env_string(value: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        default = match.group(2)
        resolved = os.getenv(key)
        if resolved is None:
            return default or ""
        return resolved

    return _ENV_PATTERN.sub(_replace, value)


def _expand_env_value(value: Any) -> Any:
    if isinstance(value, str):
        return _expand_env_string(value)
    if isinstance(value, list):
        return [_expand_env_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _expand_env_value(item) for key, item in value.items()}
    return value


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    return default


_KNOWN_PERSONA_KEYS = {"id", "display_name", "system_prompt", "style_prompt", "scope"}


def _read_personas(raw_personas: list[dict[str, Any]]) -> dict[str, PersonaConfig]:
    personas: dict[str, PersonaConfig] = {}
    for entry in raw_personas:
        entry = _expand_env_value(entry)
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
        with shared_path.open("rb") as fh:
            shared_data = tomllib.load(fh)
        shared_system = str(shared_data.get("shared_system_prompt", "")).strip()
        shared_style = str(shared_data.get("shared_style_prompt", "")).strip()

    personas: list[dict[str, Any]] = []
    for toml_file in sorted(personas_dir.glob("*.toml")):
        if toml_file.name.startswith("_"):
            continue  # skip _shared.toml and other reserved files
        with toml_file.open("rb") as fh:
            data = tomllib.load(fh)

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
        entry = _expand_env_value(entry)
        provider_id = str(entry.get("id", "")).strip()
        if not provider_id:
            continue
        raw_headers = _as_dict(entry.get("headers"))

        # Resolve style_profile reference: prepend the named profile to
        # any per-provider style_overrides so the final string is the
        # concatenation of shared + specific.
        style_text = str(entry.get("style_overrides", "")).strip()
        profile_name = str(entry.get("style_profile", "")).strip()
        if profile_name:
            if profile_name not in style_profiles:
                raise ValueError(
                    f"provider {provider_id} 引用了未知的 style_profile {profile_name!r}，"
                    f"可用：{', '.join(sorted(style_profiles))}"
                )
            shared = style_profiles[profile_name].strip()
            style_text = shared + ("\n" + style_text if style_text else "")

        providers[provider_id] = ProviderConfig(
            id=provider_id,
            protocol=str(entry.get("protocol", "")).strip().lower(),
            base_url=str(entry.get("base_url", "")).strip(),
            api_key_env=str(entry.get("api_key_env", "")).strip(),
            default_model=str(entry.get("default_model", "")).strip(),
            models=[str(item).strip() for item in entry.get("models", []) if str(item).strip()],
            non_vision_models=[str(item).strip() for item in entry.get("non_vision_models", []) if str(item).strip()],
            timeout_seconds=float(entry.get("timeout_seconds", 45)),
            temperature=float(entry.get("temperature", 0.8)),
            max_output_tokens=int(entry.get("max_output_tokens", 800)),
            style_overrides=style_text,
            stream_enabled=_as_bool(entry.get("stream_enabled", True), default=True),
            headers={str(k): str(v) for k, v in raw_headers.items()},
            user_agent=str(entry.get("user_agent", "")).strip(),
            extra_body=_expand_env_value(_as_dict(entry.get("extra_body"))),
            aliases={
                k: v
                for raw_k, raw_v in _expand_env_value(_as_dict(entry.get("aliases"))).items()
                if (k := str(raw_k).strip()) and (v := str(raw_v).strip())
            },
            fallback_urls=[str(item).strip() for item in entry.get("fallback_urls", []) if str(item).strip()],
        )
    return providers


def _read_mcp_servers(raw_servers: list[dict[str, Any]]) -> list[MCPServerConfig]:
    servers: list[MCPServerConfig] = []
    for entry in raw_servers:
        entry = _expand_env_value(entry)
        server_id = str(entry.get("id", "")).strip()
        if not server_id:
            continue

        raw_env = _as_dict(entry.get("env"))
        raw_headers = _as_dict(entry.get("headers"))
        servers.append(
            MCPServerConfig(
                id=server_id,
                transport=str(entry.get("transport", "stdio")).strip().lower() or "stdio",
                enabled=_as_bool(entry.get("enabled", True), default=True),
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

    with path.open("rb") as file:
        data = tomllib.load(file)

    personas_path = path.parent / "personas"
    raw_personas = data.get("personas", [])
    if not isinstance(raw_personas, list):
        raw_personas = []
    if personas_path.is_dir():
        raw_personas = raw_personas + _load_personas_from_dir(personas_path)
    return _read_personas(raw_personas)


def load_llm_config(path: str | Path) -> LLMConfig:
    config_path = Path(path)
    if not config_path.exists():
        return LLMConfig(load_error=f"未找到配置文件：{config_path}", source_path=config_path)

    with config_path.open("rb") as file:
        data = tomllib.load(file)

    personas = load_personas_only(config_path)

    runtime_raw = _expand_env_value(_as_dict(data.get("runtime")))
    triggers_raw = _expand_env_value(_as_dict(data.get("triggers")))
    tools_raw = _expand_env_value(_as_dict(data.get("tools")))
    mcp_raw = _expand_env_value(_as_dict(data.get("mcp")))
    daily_summary_raw = _expand_env_value(_as_dict(data.get("daily_summary")))
    daily_briefing_raw = _expand_env_value(_as_dict(data.get("daily_briefing")))
    image_preprocessing_raw = _expand_env_value(_as_dict(data.get("image_preprocessing")))
    raw_style_profiles = _expand_env_value(_as_dict(data.get("style_profiles")))
    style_profiles = {str(k).strip(): str(v).strip() for k, v in raw_style_profiles.items() if str(k).strip() and str(v).strip()}
    raw_providers = data.get("providers", [])
    raw_mcp_servers = mcp_raw.get("servers", [])
    auto_search_raw = _expand_env_value(_as_dict(triggers_raw.get("auto_search")))

    config = LLMConfig(
        runtime=RuntimeConfig(
            enabled=_as_bool(runtime_raw.get("enabled", False), default=False),
            memory_enabled=_as_bool(runtime_raw.get("memory_enabled", True), default=True),
            default_provider=str(runtime_raw.get("default_provider", "")).strip() or None,
            default_persona=str(runtime_raw.get("default_persona", "")).strip() or None,
            history_limit=int(runtime_raw.get("history_limit", 10)),
            history_max_messages_per_group=int(runtime_raw.get("history_max_messages_per_group", 40)),
            memory_limit=int(runtime_raw.get("memory_limit", 6)),
            memory_max_items_per_group=int(runtime_raw.get("memory_max_items_per_group", 200)),
            max_prompt_chars=int(runtime_raw.get("max_prompt_chars", 4000)),
            tool_calling_enabled=_as_bool(runtime_raw.get("tool_calling_enabled", False), default=False),
            tool_max_rounds=int(runtime_raw.get("tool_max_rounds", 8)),
            tool_max_calls_per_round=int(runtime_raw.get("tool_max_calls_per_round", 16)),
            retry_max_attempts=int(runtime_raw.get("retry_max_attempts", 3)),
            retry_base_delay=float(runtime_raw.get("retry_base_delay", 1.0)),
            auto_memory_enabled=_as_bool(runtime_raw.get("auto_memory_enabled", False), default=False),
            auto_memory_prompt=str(runtime_raw.get("auto_memory_prompt", "")).strip(),
            auto_memory_max_tokens=max(32, int(runtime_raw.get("auto_memory_max_tokens", 256))),
        ),
        triggers=TriggerConfig(
            default_prefix=str(triggers_raw.get("default_prefix", "/ai")).strip() or "/ai",
            allow_prefix=_as_bool(triggers_raw.get("allow_prefix", True), default=True),
            allow_at=_as_bool(triggers_raw.get("allow_at", True), default=True),
            empty_prompt_reply=str(
                triggers_raw.get("empty_prompt_reply", "请在触发指令或艾特后面补上想说的话。")
            ).strip()
            or "请在触发指令或艾特后面补上想说的话。",
        ),
        auto_search=AutoSearchConfig(
            enabled=_as_bool(auto_search_raw.get("enabled", False), default=False),
            search_max_calls_per_round=max(1, min(int(auto_search_raw.get("search_max_calls_per_round", 3)), 32)),
        ),
        tools=ToolsConfig(
            enabled=[
                str(item).strip()
                for item in tools_raw.get("enabled", [])
                if str(item).strip()
            ],
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
            enabled=_as_bool(mcp_raw.get("enabled", False), default=False),
            servers=_read_mcp_servers(raw_mcp_servers if isinstance(raw_mcp_servers, list) else []),
        ),
        providers=_read_providers(raw_providers if isinstance(raw_providers, list) else [], style_profiles=style_profiles),
        personas=personas,
        daily_summary=DailySummaryConfig(
            enabled=_as_bool(daily_summary_raw.get("enabled", False), default=False),
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
            enabled=_as_bool(daily_briefing_raw.get("enabled", False), default=False),
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
        image_preprocessing=ImagePreprocessingConfig(
            enabled=_as_bool(image_preprocessing_raw.get("enabled", False), default=False),
            provider_id=str(image_preprocessing_raw.get("provider_id", "")).strip(),
            model=str(image_preprocessing_raw.get("model", "")).strip(),
            max_tokens=max(80, int(image_preprocessing_raw.get("max_tokens", 300))),
            temperature=float(image_preprocessing_raw.get("temperature", 0.3)),
            prompt=str(image_preprocessing_raw.get("prompt", "")).strip(),
        ),
        style_profiles=style_profiles,
        source_path=config_path,
    )

    if not config.providers:
        config.load_error = "LLM 配置中没有可用的 providers"
        return config

    if config.runtime.default_provider is None:
        config.runtime.default_provider = next(iter(config.providers))

    if config.runtime.default_provider not in config.providers:
        config.load_error = f"默认 provider 不存在：{config.runtime.default_provider}"
        return config

    if not config.personas:
        config.load_error = "LLM 配置中没有可用的人格"
        return config

    if config.runtime.default_persona is None:
        config.runtime.default_persona = next(iter(config.personas))

    if config.runtime.default_persona not in config.personas:
        config.load_error = f"默认 persona 不存在：{config.runtime.default_persona}"
        return config

    if config.tools.discovery_mode not in {"off", "on", "auto"}:
        config.tools.discovery_mode = "auto"

    for provider in config.providers.values():
        if provider.protocol not in {"openai", "claude", "gemini"}:
            config.load_error = f"provider {provider.id} 使用了未知协议：{provider.protocol}"
            return config
        if not provider.base_url:
            config.load_error = f"provider {provider.id} 缺少 base_url"
            return config
        if not provider.api_key_env:
            config.load_error = f"provider {provider.id} 缺少 api_key_env"
            return config
        if not provider.default_model:
            config.load_error = f"provider {provider.id} 缺少 default_model"
            return config
        if provider.default_model not in provider.models:
            provider.models.insert(0, provider.default_model)
        for alias, target in provider.aliases.items():
            if target not in provider.models:
                config.load_error = f"provider {provider.id} 的 alias {alias!r} 指向未声明模型 {target!r}"
                return config

    return config
