"""Field constraints and override metadata for configuration writes."""

from __future__ import annotations

from dataclasses import MISSING, asdict, fields
import math
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from quickquip.llm import config as c
from quickquip.llm.config_errors import ConfigError
from quickquip.llm.skills import MAX_SCRIPT_TIMEOUT_MS

SETTINGS = {
    "runtime": c.RuntimeConfig,
    "triggers": c.TriggerConfig,
    "auto_search": c.AutoSearchConfig,
    "quick_judge": c.QuickJudgeConfig,
    "tools": c.ToolsConfig,
    "skills": c.SkillsConfig,
    "mcp": c.MCPConfig,
    "daily_summary": c.DailySummaryConfig,
    "daily_briefing": c.DailyBriefingConfig,
    "weekly_report": c.WeeklyReportConfig,
    "monthly_report": c.MonthlyReportConfig,
    "image_preprocessing": c.ImagePreprocessingConfig,
}
PROVIDER_FIXED = {
    "id",
    "protocol",
    "base_url",
    "api_key_env",
    "default_model",
    "enabled",
    "client_fingerprint",
    "fingerprint_runtime",
    "headers",
    "fallback_urls",
    "proxy",
    "auth_method",
    "models",
    "aliases",
    "non_vision_models",
    "model_context_windows",
    "model_parameters",
    "model_enabled",
    "style_profile",
    "style_append",
}
PARAMETER_TYPES = {
    k: v for k, v in get_type_hints(c.ProviderConfig).items() if k not in PROVIDER_FIXED
}
PARAMETER_TYPES["style_profile"] = str
# Numeric minima from request guard and legacy parser; values are rejected on new writes.
RANGES = {
    "timeout_seconds": (0.01, None),
    "temperature": (0, 2),
    "max_output_tokens": (1, None),
    "retry_max_attempts": (0, 20),
    "retry_base_delay": (0, None),
    "retry_jitter": (0, 1),
    "epoch_context_tokens": (1, None),
    "epoch_cold_idle_seconds": (0, None),
    "epoch_cold_target_tokens": (1, None),
    "epoch_cold_trigger_tokens": (1, None),
    "epoch_hot_target_tokens": (1, None),
    "epoch_cap_tokens": (1, None),
    "request_input_token_budget": (1, None),
    "max_inline_media_bytes": (0, None),
    "agent_replay_loop_tokens": (512, 4_194_304),
    "runtime.tool_max_rounds": (1, 16),
    "runtime.tool_max_calls_per_round": (1, 32),
    "runtime.history_limit": (0, None),
    "runtime.history_max_messages_per_group": (1, None),
    "runtime.memory_limit": (0, None),
    "runtime.memory_max_items_per_group": (1, None),
    "runtime.max_prompt_chars": (1, None),
    "runtime.auto_memory_max_tokens": (32, None),
    "runtime.recent_context_token_budget": (1, None),
    "runtime.recent_context_floor_seconds": (0, None),
    "runtime.agent_record_retention_days": (1, None),
    "runtime.agent_record_max_loops_per_scope": (1, None),
    "runtime.agent_record_max_bytes_per_scope": (1, None),
    "runtime.reply_split_threshold_chars": (80, None),
    "runtime.reply_chunk_max_chars": (80, None),
    "runtime.reply_send_interval_ms": (0, 10_000),
    "runtime.reply_max_chunks_per_loop": (1, 256),
    "runtime.mention_cooldown_seconds": (0, 86_400),
    "auto_search.search_max_calls_per_round": (1, 32),
    "quick_judge.timeout": (0.5, None),
    "quick_judge.max_tokens": (8, None),
    "tools.discovery_min_tools": (1, None),
    "tools.discovery_search_limit": (1, 20),
    "tools.discovery_max_loaded_tools": (1, 64),
    "skills.script_timeout_ms": (1, MAX_SCRIPT_TIMEOUT_MS),
    "image_preprocessing.max_tokens": (80, c.MAX_IMAGE_PREPROCESSING_TOKENS),
    "daily_summary.summary_length_hint": (100, None),
    "daily_briefing.max_context_chars": (1000, None),
    "daily_briefing.max_output_chars": (80, None),
    "weekly_report.length_hint": (200, None),
    "monthly_report.length_hint": (200, None),
    "monthly_report.input_char_budget": (8_000, None),
}
ENUMS = {
    "reasoning_effort": ("", *c.REASONING_EFFORT_CHOICES),
    "responses_profile": tuple(sorted(c.RESPONSES_PROFILE_IDS)),
    "cache_ttl": ("", "5m", "1h"),
    "tools.enabled_mode": ("append", "replace"),
    "tools.discovery_mode": ("off", "on", "auto"),
    "mcp.transport": ("stdio", "http", "sse", "docker"),
    "mcp.negotiation": ("legacy", "auto", "modern"),
    "mcp.pull_policy": ("always", "missing", "never"),
}


def reject(path: str, message: str, code: str = "invalid_field", details: Any = None) -> None:
    raise ConfigError(code, message, path, details)


def _matches(value: Any, annotation: Any) -> bool:
    origin = get_origin(annotation)
    if origin is UnionType:
        return any(_matches(value, t) for t in get_args(annotation))
    if annotation is type(None):
        return value is None
    if annotation is Any:
        return True
    if annotation is float:
        return type(value) in (float, int) and math.isfinite(value)
    if annotation in (str, int, bool):
        return type(value) is annotation
    if origin is list:
        return isinstance(value, list) and all(_matches(x, get_args(annotation)[0]) for x in value)
    if origin is dict:
        kt, vt = get_args(annotation)
        return isinstance(value, dict) and all(
            _matches(k, kt) and _matches(v, vt) for k, v in value.items()
        )
    return isinstance(value, annotation)


def check_value(value: Any, annotation: Any, path: str, rule: str, *, inherit=False) -> None:
    if value is None and inherit:
        return
    if not _matches(value, annotation):
        reject(path, "字段类型无效")
    if value is None:
        return
    bounds = RANGES.get(rule, RANGES.get(rule.rsplit(".", 1)[-1]))
    if bounds and isinstance(value, (int, float)):
        low, high = bounds
        if value < low or (high is not None and value > high):
            reject(path, "数值超出允许范围", details={"minimum": low, "maximum": high})
    choices = ENUMS.get(rule, ENUMS.get(rule.rsplit(".", 1)[-1]))
    if choices is not None and value not in choices:
        reject(path, "字段枚举无效", details={"enum": choices})


def check_fields(raw: Any, cls: type, path: str, *, exclude=()) -> dict:
    if not isinstance(raw, dict):
        reject(path, "需要对象")
    annotations = get_type_hints(cls)
    for key, value in raw.items():
        if key not in annotations or key in exclude:
            reject(f"{path}.{key}", "未知字段")
        rule = f"{path.rsplit('.', 1)[-1]}.{key}"
        check_value(value, annotations[key], f"{path}.{key}", rule)
        if cls is c.SkillsConfig and key not in ("enabled", "catalog_dir") and value <= 0:
            reject(f"{path}.{key}", "资源上限须为正整数")
        if key in (
            "min_messages",
            "active_users_limit",
            "hot_words_limit",
            "sample_messages_limit",
        ):
            if value < 1:
                reject(f"{path}.{key}", "须为正整数")
    return raw


def parameters(raw: Any, path: str) -> dict:
    if not isinstance(raw, dict):
        reject(path, "参数需要对象")
    for key, value in raw.items():
        if key not in PARAMETER_TYPES:
            reject(f"{path}.{key}", "渠道固定字段不能作为请求参数覆盖")
        check_value(value, PARAMETER_TYPES[key], f"{path}.{key}", key, inherit=True)
    return raw


def field_metadata(annotation: Any, rule: str, *, default: Any = None, inherit=False) -> dict:
    # 只有 Union/Optional 需要解包取成员；泛型本体（list[str]、dict[str, Any] 等）
    # 的 get_args 是类型参数，不能当作成员类型，否则会误判为 string。
    origin = get_origin(annotation)
    if origin in (UnionType, Union):
        args = get_args(annotation)
        nullable = type(None) in args
        base = next((x for x in args if x is not type(None)), annotation)
    else:
        nullable = False
        base = annotation
    base_origin = get_origin(base)
    kind = {str: "string", int: "integer", float: "number", bool: "boolean"}.get(
        base, {list: "array", dict: "object"}.get(base_origin, "object")
    )
    result = {"type": kind, "nullable": nullable or inherit, "inherit": inherit, "default": default}
    if rule in RANGES:
        result.update(minimum=RANGES[rule][0], maximum=RANGES[rule][1])
    elif rule.rsplit(".", 1)[-1] in RANGES:
        lo, hi = RANGES[rule.rsplit(".", 1)[-1]]
        result.update(minimum=lo, maximum=hi)
    if rule in ENUMS:
        result["enum"] = ENUMS[rule]
    elif rule.rsplit(".", 1)[-1] in ENUMS:
        result["enum"] = ENUMS[rule.rsplit(".", 1)[-1]]
    return result


def field_registry() -> dict:
    """Static field constraints, independent of deployment assets."""
    settings = {}
    for name, cls in SETTINGS.items():
        defaults = asdict(cls())
        settings[name] = {
            k: field_metadata(t, f"{name}.{k}", default=defaults[k])
            for k, t in get_type_hints(cls).items()
            if k not in ("model_cascade", "servers")
        }
    parameter_defaults = {}
    for f in fields(c.ProviderConfig):
        if f.default is not MISSING:
            parameter_defaults[f.name] = f.default
        elif f.default_factory is not MISSING:
            parameter_defaults[f.name] = f.default_factory()
    return {
        "format_version": 2,
        "settings": settings,
        "parameters": {
            k: {
                **field_metadata(t, k, default=parameter_defaults.get(k), inherit=True),
                "provider_override": True,
                "model_override": True,
            }
            for k, t in PARAMETER_TYPES.items()
        },
        "protocols": ["openai", "claude", "gemini", "openai_responses"],
        "route_names": ["daily_summary", "daily_briefing", "weekly_report", "monthly_report"],
    }


def metadata(*, config_dir=None) -> dict:
    from quickquip.llm.client_fingerprints.catalog import profile_metadata
    from quickquip.common.paths import CONFIG_DIR

    return {**field_registry(), "client_fingerprints": profile_metadata(config_dir or CONFIG_DIR)}
