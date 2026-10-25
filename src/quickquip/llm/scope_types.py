"""Persisted LLM scope configuration values."""

from dataclasses import dataclass


@dataclass(slots=True)
class GroupSettingsOverride:
    enabled: bool | None = None
    memory_enabled: bool | None = None
    auto_memory_enabled: bool | None = None
    agent_delivery_intermediate_enabled: bool | None = None
    agent_delivery_final_enabled: bool | None = None
    provider_id: str | None = None
    model: str | None = None
    persona_id: str | None = None
    trigger_prefix: str | None = None
    allow_prefix: bool | None = None
    allow_at: bool | None = None
    history_limit: int | None = None
    # 思考档位覆盖（六档词表；None = 跟随 provider 配置档）
    reasoning_effort: str | None = None
