from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ResolvedGroupSettings:
    enabled: bool
    memory_enabled: bool
    auto_memory_enabled: bool
    provider_id: str
    model: str
    persona_id: str
    trigger_prefix: str
    allow_prefix: bool
    allow_at: bool
    history_limit: int | None = None


def resolve_group_settings(store, config, group_id: int | str) -> ResolvedGroupSettings:
    overrides = store.get_group_settings(group_id)
    provider_id = overrides.provider_id or config.runtime.default_provider or ""
    provider = config.providers.get(provider_id)
    model = overrides.model or (provider.default_model if provider else "")

    return ResolvedGroupSettings(
        enabled=overrides.enabled if overrides.enabled is not None else config.runtime.enabled,
        memory_enabled=(
            overrides.memory_enabled
            if overrides.memory_enabled is not None
            else config.runtime.memory_enabled
        ),
        auto_memory_enabled=(
            overrides.auto_memory_enabled
            if overrides.auto_memory_enabled is not None
            else config.runtime.auto_memory_enabled
        ),
        provider_id=provider_id,
        model=model,
        persona_id=overrides.persona_id or config.runtime.default_persona or "",
        trigger_prefix=overrides.trigger_prefix or config.triggers.default_prefix,
        allow_prefix=(
            overrides.allow_prefix
            if overrides.allow_prefix is not None
            else config.triggers.allow_prefix
        ),
        allow_at=overrides.allow_at if overrides.allow_at is not None else config.triggers.allow_at,
        history_limit=overrides.history_limit,
    )
