"""Local-only runtime prerequisites, shared by Bot application and deployment planning."""

import os
from quickquip.llm.config_document import resolve_model_provider, environment_references
from quickquip.llm.config_errors import ConfigError


def validate_runtime_configuration(config, document):
    if config.load_error:
        raise ConfigError("configuration_failed", "Configuration could not be compiled")
    required_providers = set()
    required_models = set()

    def model(provider_id, selected, location):
        try:
            effective = resolve_model_provider(config, provider_id, selected)
            required_providers.add(provider_id)
            required_models.add((provider_id, effective.aliases.get(selected, selected)))
            return effective
        except ConfigError as exc:
            raise ConfigError(exc.code, exc.message, location, exc.details) from None

    default_id = config.runtime.default_provider or ""
    default_provider = config.providers.get(default_id)
    default_model = default_provider.default_model if default_provider else ""
    if config.runtime.enabled:
        model(default_id, default_model, "settings.runtime.default_provider")
    reports = ("daily_summary", "daily_briefing", "weekly_report", "monthly_report")
    if config.runtime.enabled or any(getattr(config, name).enabled for name in reports):
        if config.runtime.default_persona not in config.personas:
            raise ConfigError(
                "missing_persona",
                "Default persona file is missing",
                "settings.runtime.default_persona",
            )
    for name in reports:
        report = getattr(config, name)
        if not report.enabled:
            continue
        for index, entry in enumerate(report.model_cascade or ["@default"]):
            provider_id, selected = (
                (default_id, default_model) if entry == "@default" else entry.split("/", 1)
            )
            model(provider_id, selected, f"routes.{name}[{index}]")
    judge = config.quick_judge
    if judge.provider_id or judge.model:
        provider_id = judge.provider_id or default_id
        provider = config.providers.get(provider_id)
        selected = judge.model or (provider.default_model if provider else "")
        model(provider_id, selected, "settings.quick_judge")
    image = config.image_preprocessing
    if image.enabled:
        provider_id = image.provider_id
        provider = config.providers.get(provider_id)
        selected = image.model or (provider.default_model if provider else "")
        effective = model(provider_id, selected, "settings.image_preprocessing")
        wire = effective.aliases.get(selected, selected)
        if wire in effective.non_vision_models:
            raise ConfigError(
                "vision_required",
                "Image preprocessing requires a vision model",
                "settings.image_preprocessing.model",
            )
    active_providers = [
        {
            **provider,
            "models": [
                m for m in provider["models"] if (provider["id"], m["model"]) in required_models
            ],
        }
        for provider in document["providers"]
        if provider["id"] in required_providers
    ]
    missing = [
        name
        for name in environment_references({"providers": active_providers})
        if not os.getenv(name)
    ]
    if missing:
        raise ConfigError(
            "missing_environment",
            "Required environment variables missing",
            details={"variables": sorted(set(missing))},
        )
