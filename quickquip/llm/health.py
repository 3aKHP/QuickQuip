from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
import os
import sqlite3
import time
from typing import Any

from quickquip.common.paths import CONFIG_GENERATION_TOML
from quickquip.generation.config import load_generation_config
from quickquip.llm.config import LLMConfig, ProviderConfig
from quickquip.llm.settings import ResolvedGroupSettings

_PROBE_TIMEOUT_SECONDS = 5.0
_PROBE_MODEL_FALLBACK = "gpt-4o-mini"


@dataclass(slots=True)
class HealthCheckItem:
    name: str
    status: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class HealthReport:
    status: str
    scope_key: str
    chat_type: str
    duration_ms: float
    items: list[HealthCheckItem]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "scope_key": self.scope_key,
            "chat_type": self.chat_type,
            "duration_ms": self.duration_ms,
            "items": [
                {
                    "name": item.name,
                    "status": item.status,
                    "summary": item.summary,
                    "details": item.details,
                }
                for item in self.items
            ],
        }


def _overall_status(items: list[HealthCheckItem]) -> str:
    statuses = {item.status for item in items}
    if "error" in statuses:
        return "error"
    if "warn" in statuses:
        return "warn"
    return "ok"


def _env_state(env_name: str) -> str:
    if not env_name:
        return "missing-env-name"
    return "set" if os.getenv(env_name, "") else "missing"


def _check_sqlite(path: Path) -> tuple[str, str, dict[str, Any]]:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            conn.execute("SELECT 1").fetchone()
        return "ok", "SQLite 可读写", {"path": str(path), "exists": path.exists()}
    except Exception as exc:
        return "error", f"SQLite 检查失败：{exc}", {"path": str(path)}


async def _probe_provider(provider: ProviderConfig, model: str) -> tuple[bool, float, str]:
    from quickquip.llm.provider import LLMRequest, build_provider_client
    from quickquip.llm.tools import LLMConversationMessage

    request = LLMRequest(
        model=model,
        system_prompt="",
        messages=[LLMConversationMessage(role="user", content="hi")],
        temperature=0.0,
        max_output_tokens=1,
    )
    client = build_provider_client(provider)
    t0 = time.monotonic()
    try:
        await asyncio.wait_for(client.complete(request), timeout=_PROBE_TIMEOUT_SECONDS)
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        return True, latency_ms, ""
    except asyncio.TimeoutError:
        latency_ms = round(_PROBE_TIMEOUT_SECONDS * 1000)
        return False, latency_ms, "timeout"
    except Exception as exc:
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        return False, latency_ms, type(exc).__name__


async def build_health_report(
    *,
    config: LLMConfig,
    settings: ResolvedGroupSettings,
    scope_key: str,
    chat_type: str,
    db_path: Path,
    vocab_path: Path,
    identity_path: Path,
    tool_names: list[str],
    mcp_status_summary: str,
    mcp_enabled: bool,
    mcp_tool_count: int,
    recent_buffer_bound: bool,
    stats_bound: bool,
    rule_switch_bound: bool,
    include_generation: bool = True,
    generation_config_path: Path = CONFIG_GENERATION_TOML,
    probe_provider: bool = False,
    auto_memory_stats: dict[str, int] | None = None,
    image_preprocessor_bound: bool = False,
) -> HealthReport:
    started = time.monotonic()
    items: list[HealthCheckItem] = []

    if config.load_error:
        items.append(HealthCheckItem("llm_config", "error", config.load_error))
    else:
        items.append(
            HealthCheckItem(
                "llm_config",
                "ok",
                "LLM 配置已加载",
                {
                    "providers": len(config.providers),
                    "personas": len(config.personas),
                    "runtime_enabled": config.runtime.enabled,
                },
            )
        )

    provider = config.providers.get(settings.provider_id)
    if provider is None:
        items.append(
            HealthCheckItem(
                "provider",
                "error",
                f"当前 provider 不存在：{settings.provider_id}",
                {"provider_id": settings.provider_id, "model": settings.model},
            )
        )
    else:
        model_ok = settings.model in provider.models or settings.model in provider.aliases
        env_status = _env_state(provider.api_key_env)
        status = "ok" if model_ok and env_status == "set" else "warn"
        summary_parts = [f"{provider.id} / {settings.model}"]
        if not model_ok:
            summary_parts.append("模型未在 provider 中声明")
        if env_status != "set":
            summary_parts.append(f"环境变量 {provider.api_key_env or '(未配置)'} 未设置")
        details: dict[str, Any] = {
            "provider_id": provider.id,
            "protocol": provider.protocol,
            "model": settings.model,
            "model_declared": model_ok,
            "api_key_env": provider.api_key_env,
            "api_key_status": env_status,
            "timeout_seconds": provider.timeout_seconds,
        }
        if probe_provider and env_status == "set":
            reachable, probe_ms, error_type = await _probe_provider(provider, settings.model)
            details["provider_reachable"] = reachable
            details["probe_latency_ms"] = probe_ms
            if not reachable:
                details["probe_error_type"] = error_type
                summary_parts.append(f"连接探测失败（{error_type}，{probe_ms}ms）")
                status = "error"
            else:
                summary_parts.append(f"连接探测正常（{probe_ms}ms）")
        items.append(
            HealthCheckItem(
                "provider",
                status,
                "；".join(summary_parts),
                details,
            )
        )

    persona_status = "ok" if settings.persona_id in config.personas else "warn"
    items.append(
        HealthCheckItem(
            "persona",
            persona_status,
            f"当前人格：{settings.persona_id}",
            {"persona_id": settings.persona_id, "declared": settings.persona_id in config.personas},
        )
    )

    db_status, db_summary, db_details = _check_sqlite(db_path)
    items.append(HealthCheckItem("database", db_status, db_summary, db_details))

    resource_details = {
        "vocab_path": str(vocab_path),
        "vocab_exists": vocab_path.exists(),
        "identity_path": str(identity_path),
        "identity_exists": identity_path.exists(),
    }
    resource_status = "ok" if vocab_path.exists() and identity_path.exists() else "warn"
    items.append(
        HealthCheckItem(
            "knowledge_files",
            resource_status,
            "资料库文件可用" if resource_status == "ok" else "资料库文件缺失或不完整",
            resource_details,
        )
    )

    enabled_tool_count = len(tool_names)
    tool_status = "ok" if not config.runtime.tool_calling_enabled or enabled_tool_count else "warn"
    items.append(
        HealthCheckItem(
            "tools",
            tool_status,
            f"工具调用 {'开启' if config.runtime.tool_calling_enabled else '关闭'}，可用工具 {enabled_tool_count} 个",
            {"enabled": config.runtime.tool_calling_enabled, "tools": tool_names},
        )
    )

    items.append(
        HealthCheckItem(
            "mcp",
            "ok" if not mcp_enabled or mcp_tool_count else "warn",
            mcp_status_summary,
            {"enabled": mcp_enabled, "tool_count": mcp_tool_count},
        )
    )

    search_env = os.getenv("SEARXNG_BASE_URL", "").strip()
    search_needed = config.auto_search.enabled or "search_web" in tool_names
    search_status = "ok" if not search_needed or search_env else "warn"
    items.append(
        HealthCheckItem(
            "search",
            search_status,
            "搜索后端已配置" if search_env else "搜索后端未配置",
            {"needed": search_needed, "base_url_configured": bool(search_env)},
        )
    )

    img_cfg = config.image_preprocessing
    img_provider = config.providers.get(img_cfg.provider_id) if img_cfg.provider_id else None
    if not img_cfg.enabled:
        image_status = "ok"
        image_summary = "图片预处理未启用"
    elif img_provider is None:
        image_status = "warn"
        image_summary = f"图片预处理 provider 不存在：{img_cfg.provider_id}"
    elif not image_preprocessor_bound:
        image_status = "warn"
        image_summary = "图片预处理已配置但运行时未绑定"
    else:
        image_status = "ok"
        image_summary = f"图片预处理已绑定：{img_cfg.provider_id} / {img_cfg.model or img_provider.default_model}"
    items.append(
        HealthCheckItem(
            "image_preprocessing",
            image_status,
            image_summary,
            {
                "enabled": img_cfg.enabled,
                "provider_id": img_cfg.provider_id,
                "provider_declared": img_provider is not None,
                "model": img_cfg.model or (img_provider.default_model if img_provider else ""),
                "runtime_bound": image_preprocessor_bound,
            },
        )
    )

    if include_generation:
        generation = load_generation_config(generation_config_path)
        if generation.load_error:
            items.append(HealthCheckItem("generation", "warn", generation.load_error))
        else:
            items.append(
                HealthCheckItem(
                    "generation",
                    "ok",
                    "生成配置已加载",
                    {
                        "image_models": len(generation.image.models),
                        "audio_models": len(generation.audio.models),
                        "music_models": len(generation.music.models),
                    },
                )
            )

    if auto_memory_stats is not None:
        successes = auto_memory_stats.get("successes", 0)
        failures = auto_memory_stats.get("failures", 0)
        active_scopes = auto_memory_stats.get("active_scopes", 0)
        total = successes + failures
        fail_rate = f"{failures / total:.1%}" if total else "N/A"
        status = "ok" if failures == 0 or (total and failures / total < 0.3) else "warn"
        items.append(
            HealthCheckItem(
                "auto_memory",
                status,
                f"已抽取 {successes} 次 / 失败 {failures} 次 / {active_scopes} 个活跃 scope",
                {
                    "successes": successes,
                    "failures": failures,
                    "fail_rate": fail_rate,
                    "active_scopes": active_scopes,
                    "batch_interval_turns": 10,
                },
            )
        )

    bindings_ok = recent_buffer_bound and (chat_type == "private" or (stats_bound and rule_switch_bound))
    items.append(
        HealthCheckItem(
            "runtime_bindings",
            "ok" if bindings_ok else "warn",
            "运行时依赖已绑定" if bindings_ok else "部分运行时依赖未绑定",
            {
                "recent_message_buffer": recent_buffer_bound,
                "stats_tracker": stats_bound,
                "rule_switch": rule_switch_bound,
            },
        )
    )

    elapsed_ms = round((time.monotonic() - started) * 1000, 1)
    return HealthReport(
        status=_overall_status(items),
        scope_key=scope_key,
        chat_type=chat_type,
        duration_ms=elapsed_ms,
        items=items,
    )


def format_health_report(report: HealthReport, *, verbose: bool = False) -> str:
    icon = {"ok": "✅", "warn": "⚠️", "error": "❌"}.get(report.status, "ℹ️")
    lines = [f"{icon} LLM 健康检查：{report.status.upper()}（{report.duration_ms}ms）"]
    for item in report.items:
        item_icon = {"ok": "✅", "warn": "⚠️", "error": "❌"}.get(item.status, "ℹ️")
        lines.append(f"{item_icon} {item.name}：{item.summary}")
        if verbose and item.details:
            for key, value in item.details.items():
                lines.append(f"  - {key}: {value}")
    return "\n".join(lines)
