from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import tomllib


@dataclass(slots=True)
class TriggerConfig:
    default_prefix: str = "/ai"
    allow_prefix: bool = True
    allow_at: bool = True
    empty_prompt_reply: str = "请在触发指令或艾特后面补上想说的话。"


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


@dataclass(slots=True)
class PersonaConfig:
    id: str
    display_name: str
    system_prompt: str
    style_prompt: str = ""


@dataclass(slots=True)
class ProviderConfig:
    id: str
    protocol: str
    base_url: str
    api_key_env: str
    default_model: str
    models: list[str]
    timeout_seconds: float = 45.0
    temperature: float = 0.8
    max_output_tokens: int = 800
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class LLMConfig:
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    triggers: TriggerConfig = field(default_factory=TriggerConfig)
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    personas: dict[str, PersonaConfig] = field(default_factory=dict)
    load_error: str | None = None
    source_path: Path | None = None

    @property
    def is_available(self) -> bool:
        return self.load_error is None and self.runtime.enabled and bool(self.providers)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _read_personas(raw_personas: list[dict[str, Any]]) -> dict[str, PersonaConfig]:
    personas: dict[str, PersonaConfig] = {}
    for entry in raw_personas:
        persona_id = str(entry.get("id", "")).strip()
        if not persona_id:
            continue
        personas[persona_id] = PersonaConfig(
            id=persona_id,
            display_name=str(entry.get("display_name", persona_id)).strip() or persona_id,
            system_prompt=str(entry.get("system_prompt", "")).strip(),
            style_prompt=str(entry.get("style_prompt", "")).strip(),
        )
    return personas


def _read_providers(raw_providers: list[dict[str, Any]]) -> dict[str, ProviderConfig]:
    providers: dict[str, ProviderConfig] = {}
    for entry in raw_providers:
        provider_id = str(entry.get("id", "")).strip()
        if not provider_id:
            continue
        raw_headers = _as_dict(entry.get("headers"))
        providers[provider_id] = ProviderConfig(
            id=provider_id,
            protocol=str(entry.get("protocol", "")).strip().lower(),
            base_url=str(entry.get("base_url", "")).strip(),
            api_key_env=str(entry.get("api_key_env", "")).strip(),
            default_model=str(entry.get("default_model", "")).strip(),
            models=[str(item).strip() for item in entry.get("models", []) if str(item).strip()],
            timeout_seconds=float(entry.get("timeout_seconds", 45)),
            temperature=float(entry.get("temperature", 0.8)),
            max_output_tokens=int(entry.get("max_output_tokens", 800)),
            headers={str(k): str(v) for k, v in raw_headers.items()},
        )
    return providers


def load_llm_config(path: str | Path) -> LLMConfig:
    config_path = Path(path)
    if not config_path.exists():
        return LLMConfig(load_error=f"未找到配置文件：{config_path}", source_path=config_path)

    with config_path.open("rb") as file:
        data = tomllib.load(file)

    runtime_raw = _as_dict(data.get("runtime"))
    triggers_raw = _as_dict(data.get("triggers"))
    raw_providers = data.get("providers", [])
    raw_personas = data.get("personas", [])

    config = LLMConfig(
        runtime=RuntimeConfig(
            enabled=bool(runtime_raw.get("enabled", False)),
            memory_enabled=bool(runtime_raw.get("memory_enabled", True)),
            default_provider=str(runtime_raw.get("default_provider", "")).strip() or None,
            default_persona=str(runtime_raw.get("default_persona", "")).strip() or None,
            history_limit=int(runtime_raw.get("history_limit", 10)),
            history_max_messages_per_group=int(runtime_raw.get("history_max_messages_per_group", 40)),
            memory_limit=int(runtime_raw.get("memory_limit", 6)),
            memory_max_items_per_group=int(runtime_raw.get("memory_max_items_per_group", 200)),
            max_prompt_chars=int(runtime_raw.get("max_prompt_chars", 4000)),
        ),
        triggers=TriggerConfig(
            default_prefix=str(triggers_raw.get("default_prefix", "/ai")).strip() or "/ai",
            allow_prefix=bool(triggers_raw.get("allow_prefix", True)),
            allow_at=bool(triggers_raw.get("allow_at", True)),
            empty_prompt_reply=str(
                triggers_raw.get("empty_prompt_reply", "请在触发指令或艾特后面补上想说的话。")
            ).strip()
            or "请在触发指令或艾特后面补上想说的话。",
        ),
        providers=_read_providers(raw_providers if isinstance(raw_providers, list) else []),
        personas=_read_personas(raw_personas if isinstance(raw_personas, list) else []),
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

    return config
