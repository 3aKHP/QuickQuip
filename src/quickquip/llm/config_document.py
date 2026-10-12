"""Strict JSON exchange, reference validation and runtime configuration compilation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit, parse_qsl

from quickquip.common.config_utils import expand_env_value
from quickquip.common.paths import CONFIG_DIR
from quickquip.llm import config as c
from quickquip.llm.config_errors import ConfigError
from quickquip.llm.config_fields import (
    SETTINGS,
    PARAMETER_TYPES,
    check_fields,
    check_value,
    parameters,
    reject,
    metadata,
)
from quickquip.llm.personas import load_personas

__all__ = [
    "ConfigError",
    "empty_document",
    "validate_document",
    "compile_document",
    "metadata",
    "dependencies",
    "resolve_model_provider",
    "effective_parameters",
    "environment_references",
]
FORMAT_VERSION = 1
ROUTES = ("daily_summary", "daily_briefing", "weekly_report", "monthly_report")
_VARIABLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_SECRET_KEY = re.compile(
    r"(?:(?:.*[-_])?authorization|x-api-key|key|api[_-]?key|access[_-]?token|"
    r"refresh[_-]?token|token|password|secret|cookie|.*[_-](?:token|secret|password|key))$",
    re.I,
)


def empty_document() -> dict:
    settings = {name: asdict(cls()) for name, cls in SETTINGS.items()}
    for name in ROUTES:
        settings[name].pop("model_cascade")
    return {
        "format_version": FORMAT_VERSION,
        "providers": [],
        "style_profiles": {},
        "pricing": [],
        "routes": {name: [] for name in ROUTES},
        "settings": settings,
    }


def _object(value: Any, path: str, allowed: set[str] | None = None) -> dict:
    if not isinstance(value, dict):
        reject(path, "需要对象")
    if allowed is not None:
        for key in value:
            if key not in allowed:
                reject(f"{path}.{key}", "未知字段")
    return value


def _list(value: Any, path: str) -> list:
    if not isinstance(value, list):
        reject(path, "需要数组")
    return value


def _text(value: Any, path: str, *, nonempty=False) -> str:
    if not isinstance(value, str) or (nonempty and not value.strip()):
        reject(path, "需要非空字符串" if nonempty else "需要字符串")
    if "\x00" in value:
        reject(path, "字符串包含非法字符")
    return value


def _secrets(value: Any, path: str = "") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            location = f"{path}.{key}" if path else key
            if _SECRET_KEY.fullmatch(key) and child:
                if not isinstance(child, str) or not _REFERENCE.search(child):
                    reject(location, "认证值须迁入根目录 .env 并保存变量引用", "literal_secret")
                residual = _REFERENCE.sub("", child).strip()
                if residual.lower() not in ("", "bearer", "basic"):
                    reject(location, "认证字段只允许环境变量引用", "literal_secret")
            _secrets(child, location)
    elif isinstance(value, list):
        for i, child in enumerate(value):
            _secrets(child, f"{path}[{i}]")
    elif isinstance(value, str):
        try:
            parts = urlsplit(value)
        except ValueError:
            reject(path, "地址格式无效")
        if parts.scheme not in ("http", "https"):
            return
        if parts.username or parts.password:
            reject(path, "地址中的认证值须使用独立变量引用", "literal_secret")
        for key, child in parse_qsl(parts.query):
            if _SECRET_KEY.fullmatch(key) and child:
                if not _REFERENCE.search(child) or _REFERENCE.sub("", child).strip():
                    reject(path, "地址中的认证值须完全使用环境变量引用", "literal_secret")


def environment_references(doc: dict) -> list[str]:
    found = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "api_key_env" and child:
                    found.add(child)
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, str):
            found.update(_REFERENCE.findall(value))

    visit(doc)
    return sorted(found)


def _validate_mcp(raw: dict) -> dict:
    _object(raw, "settings.mcp", {"enabled", "servers"})
    check_value(raw.get("enabled", False), bool, "settings.mcp.enabled", "enabled")
    result = {"enabled": raw.get("enabled", False), "servers": []}
    seen = set()
    for i, server in enumerate(_list(raw.get("servers", []), "settings.mcp.servers")):
        path = f"settings.mcp.servers[{i}]"
        check_fields(server, c.MCPServerConfig, path)
        ident = _text(server.get("id"), path + ".id", nonempty=True)
        if ident in seen:
            reject(path + ".id", "MCP ID 重复")
        seen.add(ident)
        item = asdict(c.MCPServerConfig(**server))
        for key in ("transport", "negotiation", "pull_policy"):
            check_value(item[key], str, path + "." + key, "mcp." + key)
        if item["negotiation"] != "legacy":
            if item["transport"] != "http" or not item["supported_protocol_versions"]:
                reject(path, "auto/modern 协商需要 HTTP 与支持的协议版本")
        result["servers"].append(item)
    return result


def validate_document(document: Any) -> dict:
    """Normalize a complete replacement; no secret expansion or silent clamping."""
    allowed = {"format_version", "providers", "style_profiles", "pricing", "routes", "settings"}
    _object(document, "", allowed)
    if type(document.get("format_version")) is not int or document["format_version"] != 1:
        reject("format_version", "不支持的配置交换格式", "unsupported_format")
    _secrets(document)
    # Enforce JSON and reject NaN, unserializable objects and deep non-string key coercion.
    try:
        doc = json.loads(json.dumps(document, ensure_ascii=False, allow_nan=False))
    except (ValueError, TypeError, RecursionError):
        reject("", "配置须为合法 JSON")
    output = empty_document()
    styles = _object(doc.get("style_profiles", {}), "style_profiles")
    for key, value in styles.items():
        _text(key, "style_profiles", nonempty=True)
        _text(value, f"style_profiles.{key}")
    output["style_profiles"] = styles
    providers = _list(doc.get("providers", []), "providers")
    ids = set()
    models = {}
    for i, raw in enumerate(providers):
        path = f"providers[{i}]"
        _object(
            raw,
            path,
            {
                "id",
                "protocol",
                "base_url",
                "api_key_env",
                "default_model",
                "enabled",
                "headers",
                "fallback_urls",
                "proxy",
                "auth_method",
                "parameters",
                "models",
                "aliases",
            },
        )
        ident = _text(raw.get("id"), path + ".id", nonempty=True)
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", ident) or ident in ids:
            reject(path + ".id", "渠道 ID 须唯一且仅含字母、数字、点、下划线及连字符")
        ids.add(ident)
        if raw.get("protocol") not in metadata()["protocols"]:
            reject(path + ".protocol", "不支持的协议")
        for key in ("base_url", "api_key_env", "default_model"):
            _text(raw.get(key), path + "." + key, nonempty=True)
        if not _VARIABLE.fullmatch(raw["api_key_env"]):
            reject(path + ".api_key_env", "需要环境变量名称")
        if raw.get("auth_method", "api_key") not in ("api_key", "bearer"):
            reject(path + ".auth_method", "认证方式无效")
        base = {
            "enabled": True,
            "headers": {},
            "fallback_urls": [],
            "proxy": "",
            "auth_method": "api_key",
            "aliases": [],
            "parameters": {},
        }
        base.update(raw)
        check_value(base["enabled"], bool, path + ".enabled", "enabled")
        check_value(base["headers"], dict[str, str], path + ".headers", "headers")
        check_value(base["fallback_urls"], list[str], path + ".fallback_urls", "fallback_urls")
        _text(base["proxy"], path + ".proxy")
        parameters(base["parameters"], path + ".parameters")
        names = set()
        entries = []
        for j, entry in enumerate(_list(raw.get("models", []), path + ".models")):
            location = f"{path}.models[{j}]"
            _object(entry, location, {"model", "enabled", "vision", "context_window", "parameters"})
            name = _text(entry.get("model"), location + ".model", nonempty=True)
            if name in names:
                reject(location + ".model", "模型名重复")
            names.add(name)
            model = {"enabled": True, "vision": True, "context_window": None, "parameters": {}}
            model.update(entry)
            for key in ("enabled", "vision"):
                check_value(model[key], bool, location + "." + key, key)
            capacity = model["context_window"]
            if capacity is not None and (type(capacity) is not int or capacity < 1024):
                reject(location + ".context_window", "模型容量须为至少 1024 的整数或 null")
            parameters(model["parameters"], location + ".parameters")
            entries.append(model)
        base["models"] = entries
        models[ident] = names
        if base["default_model"] not in names:
            reject(path + ".default_model", "默认模型不存在", "dependency_conflict")
        aliases = set()
        for j, alias in enumerate(_list(base["aliases"], path + ".aliases")):
            location = f"{path}.aliases[{j}]"
            _object(alias, location, {"alias", "model"})
            name = _text(alias.get("alias"), location + ".alias", nonempty=True)
            if name in aliases or name in names:
                reject(location + ".alias", "别名重复或与模型名冲突")
            aliases.add(name)
            if alias.get("model") not in names:
                reject(location + ".model", "别名目标不存在", "dependency_conflict")
        for request in [base["parameters"], *[m["parameters"] for m in entries]]:
            style = request.get("style_profile")
            if style and style not in styles:
                reject(path + ".parameters.style_profile", "风格引用不存在", "dependency_conflict")
        output["providers"].append(base)
    raw_settings = _object(doc.get("settings", {}), "settings", set(SETTINGS))
    for name, cls in SETTINGS.items():
        raw = raw_settings.get(name, {})
        if name == "mcp":
            output["settings"][name] = _validate_mcp(raw)
        else:
            check_fields(raw, cls, "settings." + name, exclude=("model_cascade",))
            output["settings"][name].update(raw)
    rt = output["settings"]["runtime"]
    if rt["default_provider"] is not None and rt["default_provider"] not in ids:
        reject("settings.runtime.default_provider", "默认渠道不存在", "dependency_conflict")
    if rt["enabled"] and not providers:
        reject("settings.runtime.enabled", "启用 LLM 需要至少一个渠道")
    if rt["reply_split_threshold_chars"] > rt["reply_chunk_max_chars"]:
        reject("settings.runtime.reply_split_threshold_chars", "拆分阈值不能超过分段上限")
    routes = _object(doc.get("routes", {}), "routes", set(ROUTES))
    for name in ROUTES:
        output["routes"][name] = _list(routes.get(name, []), "routes." + name)
        for j, entry in enumerate(output["routes"][name]):
            location = f"routes.{name}[{j}]"
            if entry == "@default":
                continue
            _reference(entry, models, location)
    for name in ("quick_judge", "image_preprocessing"):
        selection = output["settings"][name]
        if selection["provider_id"]:
            _reference(
                {"provider_id": selection["provider_id"], "model": selection["model"]},
                models,
                "settings." + name,
                allow_default=True,
            )
        elif selection["model"]:
            reject("settings." + name + ".provider_id", "指定模型需要渠道")
    seen_prices = set()
    for i, entry in enumerate(_list(doc.get("pricing", []), "pricing")):
        location = f"pricing[{i}]"
        _object(entry, location, {"provider_id", "model", *asdict(c.PricingRates())})
        _text(entry.get("model"), location + ".model", nonempty=True)
        provider = entry.get("provider_id")
        if provider is not None:
            _text(provider, location + ".provider_id", nonempty=True)
        price_id = (provider, entry["model"])
        if price_id in seen_prices:
            reject(location, "价格规则重复")
        seen_prices.add(price_id)
        rates = {k: v for k, v in entry.items() if k not in ("provider_id", "model")}
        check_fields(rates, c.PricingRates, location)
        for key, value in rates.items():
            if key.endswith("per_mtok") and value is not None and value < 0:
                reject(location + "." + key, "价格须为非负数或 null")
        output["pricing"].append(
            {"provider_id": provider, "model": entry["model"], **asdict(c.PricingRates(**rates))}
        )
    _validate_epoch_graph(output)
    return output


def _reference(entry: Any, models: dict, path: str, *, allow_default=False) -> None:
    _object(entry, path, {"provider_id", "model"})
    provider, model = entry.get("provider_id"), entry.get("model")
    if provider not in models or (
        model not in models[provider] and not (allow_default and model == "")
    ):
        reject(path, "渠道或模型引用不存在", "dependency_conflict", {"reference": entry})


def _validate_epoch_graph(doc: dict) -> None:
    runtime = c.RuntimeConfig(**doc["settings"]["runtime"])
    config = c.LLMConfig(runtime=runtime)
    pairs = c._EPOCH_OVERRIDE_PAIRS
    from quickquip.llm.epoch import EpochParams

    def valid(overrides: dict, path: str) -> None:
        values = {
            p: overrides.get(k) if overrides.get(k) is not None else getattr(runtime, k)
            for k, p in pairs
        }
        if not c._epoch_params_valid(EpochParams(**values)):
            reject(path, "纪元参数须满足 0 < cold_target < cold_trigger ≤ hot_target < cap")

    valid({}, "settings.runtime")
    del config
    for provider in doc["providers"]:
        valid(provider["parameters"], f"providers.{provider['id']}.parameters")
        for model in provider["models"]:
            merged = {k: v for k, v in provider["parameters"].items() if v is not None}
            merged.update({k: v for k, v in model["parameters"].items() if v is not None})
            valid(merged, f"providers.{provider['id']}.models.{model['model']}.parameters")


def dependencies(document: dict) -> list[dict]:
    """List config edges using public identities, including disabled features."""
    edges = []

    def edge(path: str, provider: str, model: str | None = None) -> None:
        target = {"provider_id": provider}
        if model:
            target["model"] = model
        edges.append({"field_path": path, "target": target})

    rt = document["settings"]["runtime"]
    if rt["default_provider"]:
        edge("settings.runtime.default_provider", rt["default_provider"])
    for name, entries in document["routes"].items():
        for i, entry in enumerate(entries):
            if entry != "@default":
                edge(f"routes.{name}[{i}]", entry["provider_id"], entry["model"])
    for name in ("quick_judge", "image_preprocessing"):
        s = document["settings"][name]
        if s["provider_id"]:
            edge("settings." + name, s["provider_id"], s["model"])
    for provider in document["providers"]:
        pid = provider["id"]
        edge(f"providers.{pid}.default_model", pid, provider["default_model"])
        for alias in provider["aliases"]:
            edge(f"providers.{pid}.aliases.{alias['alias']}", pid, alias["model"])
        for location, params in [
            (f"providers.{pid}.parameters", provider["parameters"]),
            *[
                (f"providers.{pid}.models.{m['model']}.parameters", m["parameters"])
                for m in provider["models"]
            ],
        ]:
            if params.get("style_profile"):
                edges.append(
                    {
                        "field_path": location + ".style_profile",
                        "target": {"style_profile": params["style_profile"]},
                    }
                )
    return edges


def compile_document(
    document: dict, config_dir: Path | str | None = None, revision=0
) -> c.LLMConfig:
    doc = validate_document(document)
    directory = Path(config_dir) if config_dir is not None else CONFIG_DIR
    config = c.LLMConfig(revision=revision, source_path=directory.parent / "data/llm_config.db")
    for name, cls in SETTINGS.items():
        if name == "mcp":
            mcp = doc["settings"][name]
            config.mcp = c.MCPConfig(
                enabled=mcp["enabled"],
                servers=[c.MCPServerConfig(**expand_env_value(s)) for s in mcp["servers"]],
            )
        else:
            setattr(config, name, cls(**deepcopy(doc["settings"][name])))
    config.personas = load_personas(directory / "personas")
    config.style_profiles = deepcopy(expand_env_value(doc["style_profiles"]))
    for raw in doc["providers"]:
        fixed = {
            k: expand_env_value(raw[k])
            for k in (
                "id",
                "protocol",
                "base_url",
                "api_key_env",
                "default_model",
                "enabled",
                "headers",
                "fallback_urls",
                "proxy",
                "auth_method",
            )
        }
        values = {k: expand_env_value(v) for k, v in raw["parameters"].items() if v is not None}
        profile = values.pop("style_profile", "")
        append = values.get("style_overrides", "")
        fixed.update(values)
        provider = c.ProviderConfig(**fixed, models=[m["model"] for m in raw["models"]])
        provider.model_parameters = {m["model"]: deepcopy(m["parameters"]) for m in raw["models"]}
        provider.model_enabled = {m["model"]: m["enabled"] for m in raw["models"]}
        provider.non_vision_models = [m["model"] for m in raw["models"] if not m["vision"]]
        provider.model_context_windows = {
            m["model"]: m["context_window"]
            for m in raw["models"]
            if m["context_window"] is not None
        }
        provider.aliases = {a["alias"]: a["model"] for a in raw["aliases"]}
        provider.style_profile, provider.style_append = profile, append
        provider.style_overrides = _style(config, profile, append)
        for key in ("retry_max_attempts", "retry_base_delay", "retry_jitter"):
            if raw["parameters"].get(key) is None:
                setattr(provider, key, getattr(config.runtime, key))
        config.providers[provider.id] = provider
    if config.runtime.default_provider is None and config.providers:
        config.runtime.default_provider = next(
            (p.id for p in config.providers.values() if p.enabled), next(iter(config.providers))
        )
    if config.runtime.default_persona is None and config.personas:
        config.runtime.default_persona = next(iter(config.personas))
    for name in ROUTES:
        getattr(config, name).model_cascade = [
            "@default" if e == "@default" else f"{e['provider_id']}/{e['model']}"
            for e in doc["routes"][name]
        ]
    for price in doc["pricing"]:
        name = price["model"]
        if price["provider_id"]:
            name = price["provider_id"] + "/" + name
        rates = c.PricingRates(
            **{k: v for k, v in price.items() if k not in ("provider_id", "model")}
        )
        config.pricing_references[(price["provider_id"], price["model"])] = rates
        config.pricing[name] = rates
    return config


def _style(config: c.LLMConfig, profile: str, append: str) -> str:
    shared = config.style_profiles.get(profile, "")
    return shared + ("\n" + append if shared and append else append)


def resolve_model_provider(
    config: c.LLMConfig, provider_id: str, model: str, overrides: dict | None = None
) -> c.ProviderConfig:
    provider = config.providers.get(provider_id)
    if provider is None:
        reject("provider_id", "渠道不存在", "dependency_conflict")
    wire = provider.aliases.get(model, model or provider.default_model)
    if wire not in provider.models:
        reject("model", "模型不存在", "dependency_conflict")
    if not provider.enabled or not provider.model_enabled.get(wire, True):
        reject("model", "渠道或模型已停用", "disabled_model")
    changes = {
        k: expand_env_value(v)
        for k, v in provider.model_parameters.get(wire, {}).items()
        if v is not None
    }
    if overrides:
        parameters(overrides, "overrides")
        changes.update({k: v for k, v in overrides.items() if v is not None})
    profile = changes.pop("style_profile", provider.style_profile)
    append = changes.pop(
        "style_overrides",
        provider.style_append if provider.style_append is not None else provider.style_overrides,
    )
    if "style_overrides" not in changes:
        changes["style_overrides"] = _style(config, profile, append)
    changes.update(style_profile=profile, style_append=append)
    result = replace(provider, **changes)
    return result


def effective_parameters(document: dict, provider_id: str, model: str) -> dict:
    """Return unexpanded values and source for UI; never expose resolved credentials."""
    doc = validate_document(document)
    provider = next((p for p in doc["providers"] if p["id"] == provider_id), None)
    if provider is None:
        reject("provider_id", "渠道不存在", "dependency_conflict")
    entry = next((m for m in provider["models"] if m["model"] == model), None)
    if entry is None:
        reject("model", "模型不存在", "dependency_conflict")
    defaults = c.ProviderConfig("", "", "", "", "", [])
    output = {}
    for key in PARAMETER_TYPES:
        value = getattr(defaults, key, "")
        source = "builtin"
        if (
            key.startswith("epoch_")
            or key.startswith("retry_")
            or key in ("request_input_token_budget", "agent_replay_loop_tokens")
        ):
            value = doc["settings"]["runtime"][key]
            source = "runtime"
        configured = {
            "provider": provider["parameters"].get(key),
            "model": entry["parameters"].get(key),
        }
        for layer, params in (("provider", provider["parameters"]), ("model", entry["parameters"])):
            if params.get(key) is not None:
                value, source = params[key], layer
        output[key] = {"configured": configured, "value": value, "source": source}
    from quickquip.llm.context_windows import resolve_context_window

    # Capacity lookup uses explicit windows and the existing model family registry.
    provider_config = c.ProviderConfig("", "", "", "", "", [])
    if entry["context_window"] is not None:
        provider_config.model_context_windows[model] = entry["context_window"]
    capacity = resolve_context_window(provider_config.model_context_windows, model)
    output["context_window"] = {
        "configured": entry["context_window"],
        "value": capacity,
        "source": "model"
        if entry["context_window"] is not None
        else "automatic"
        if capacity
        else "unknown",
    }
    return output
