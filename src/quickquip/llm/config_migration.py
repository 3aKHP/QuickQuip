"""One-time legacy migration with recoverable asset preparation and private backups."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
import tempfile
from pathlib import Path
import tomllib
from typing import Any

from filelock import FileLock

from quickquip.llm.config_document import (
    ROUTES,
    _secrets,
    empty_document,
    validate_document,
)
from quickquip.llm.config_fields import PARAMETER_TYPES, RANGES
from quickquip.llm.config_errors import ConfigError
from quickquip.llm.config_durability import durable_write, sync_directory
from quickquip.llm.config_legacy import load_llm_config


def _literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_literal(v) for v in value) + "]"
    if isinstance(value, dict):
        return (
            "{ "
            + ", ".join(f"{_literal(k)} = {_literal(v)}" for k, v in value.items() if v is not None)
            + " }"
        )
    raise ConfigError("migration_asset_error", "无法编码旧配置字段")


def _toml(data: dict) -> str:
    """Inline TOML values preserve nesting and avoid table ownership ambiguity."""
    return (
        "\n".join(f"{_literal(k)} = {_literal(v)}" for k, v in data.items() if v is not None) + "\n"
    )


def _write_asset(target: Path, data: dict, backup_dir: Path, report: dict) -> None:
    content = _toml(data)
    # Validate generated asset before any write.
    tomllib.loads(content)
    target.parent.mkdir(parents=True, exist_ok=True)
    sync_directory(target.parent.parent)
    staged = backup_dir / (target.name + ".staged")
    durable_write(staged, content.encode("utf-8"))
    report["assets"].append({"file": str(target.name), "status": "prepared"})
    journal = backup_dir / "report.json"
    durable_write(journal, (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
    if target.exists():
        if target.read_text(encoding="utf-8") != content:
            raise ConfigError(
                "migration_asset_conflict", "目标文件已存在，请检查迁移报告", target.name
            )
    else:
        # Publish a complete file on the target filesystem without overwriting another writer.
        descriptor, name = tempfile.mkstemp(prefix=".llm-migration-", dir=target.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, target)
            sync_directory(target.parent)
        finally:
            temporary.unlink(missing_ok=True)
    report["assets"][-1]["status"] = "ready"


def _prepare_assets(path: Path, raw: dict, report: dict, backup: Path) -> None:
    personas_dir = path.parent / "personas"
    existing_ids = set()
    if personas_dir.exists():
        for file in personas_dir.glob("*.toml"):
            if file.name.startswith("_"):
                continue
            try:
                data = tomllib.loads(file.read_text(encoding="utf-8"))
            except tomllib.TOMLDecodeError:
                raise ConfigError("migration_asset_conflict", "独立人格文件语法错误", file.name)
            entries = [data] if "id" in data else data.get("personas", [])
            existing_ids.update(e.get("id") for e in entries)
    inline = {}
    for item in raw.get("personas", []):
        inline[item.get("id", "")] = item
    for i, persona in enumerate(inline.values()):
        ident = persona.get("id", "")
        if not ident:
            report["warnings"].append({"field_path": f"personas[{i}]", "code": "empty_persona"})
            continue
        digest = hashlib.sha256(ident.encode()).hexdigest()[:16]
        target = personas_dir / f"migrated-{digest}.toml"
        data = {**persona, "inherit_shared": False}
        if ident in existing_ids:
            # An interrupted extraction's exact file may already exist.
            if target.exists() and target.read_text(encoding="utf-8") == _toml(data):
                report["assets"].append({"file": target.name, "status": "ready"})
            else:
                report["warnings"].append(
                    {"field_path": f"personas[{i}]", "code": "independent_persona_authoritative"}
                )
            continue
        _write_asset(target, data, backup, report)
    generation = raw.get("generation", {})
    if not isinstance(generation, dict):
        raise ConfigError("migration_asset_error", "旧 generation 字段需要对象")
    sections = dict(generation)
    for name in ("image", "audio", "music", "asr", "svg"):
        value = raw.get(name, raw.get(name + "_generation"))
        if name not in sections and value:
            sections[name] = value
    if sections:
        target = path.parent / "generation.toml"
        if target.exists():
            report["warnings"].append(
                {"field_path": "generation", "code": "independent_generation_authoritative"}
            )
        else:
            _secrets(sections, "generation")
            _write_asset(target, {"generation": sections}, backup, report)


def migrate_legacy(path: str | Path) -> tuple[dict, dict]:
    """Return a strict document after asset preparation; never delete the legacy source."""
    path = Path(path)
    try:
        original = path.read_bytes()
        raw = tomllib.loads(original.decode("utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        raise ConfigError("invalid_legacy", "旧 LLM 配置无法读取或解析") from None
    _secrets(raw)
    data_dir = path.parent.parent / "data" if path.parent.name == "config" else path.parent / "data"
    digest = hashlib.sha256(original).hexdigest()
    backup = data_dir / "llm-config-migration" / digest[:16]
    backup.mkdir(parents=True, exist_ok=True)
    with FileLock(str(backup / "migration.lock"), timeout=10):
        report = {
            "format_version": 1,
            "source_sha256": digest,
            "changes": [],
            "warnings": [],
            "assets": [],
            "backup": str(backup),
        }
        source_copy = backup / "llm.toml"
        if (
            not source_copy.exists()
            or hashlib.sha256(source_copy.read_bytes()).hexdigest() != digest
        ):
            durable_write(source_copy, original)
        complete = backup / "assets-backup-complete.json"
        if not complete.exists():
            manifest = {}
            for source in (path.parent / "personas", path.parent / "generation.toml"):
                if not source.exists():
                    continue
                files = sorted(source.rglob("*")) if source.is_dir() else [source]
                for file in files:
                    if not file.is_file():
                        continue
                    relative = file.relative_to(path.parent)
                    contents = file.read_bytes()
                    target = backup / relative
                    # Repeat unfinished backup writes; originals are still authoritative here.
                    durable_write(target, contents)
                    manifest[str(relative)] = hashlib.sha256(contents).hexdigest()
            durable_write(complete, json.dumps(manifest, sort_keys=True).encode())
            sync_directory(backup.parent)
            sync_directory(backup.parent.parent)
        manifest = json.loads(complete.read_text())
        for relative, expected in manifest.items():
            asset = backup / relative
            if not asset.is_file() or hashlib.sha256(asset.read_bytes()).hexdigest() != expected:
                raise ConfigError("migration_backup_invalid", "迁移回退资产缺失或损坏", relative)
        # The frozen parser consumes the captured original and independent asset backup.
        legacy = load_llm_config(source_copy, preserve_env=True)
        doc = empty_document()
        for name in doc["settings"]:
            value = asdict(getattr(legacy, name))
            value.pop("model_cascade", None)
            doc["settings"][name] = value
        doc["style_profiles"] = dict(legacy.style_profiles)
        doc["settings"]["tools"]["enabled_mode"] = legacy.tools.enabled_mode
        if "enabled_mode" not in raw.get("tools", {}):
            report["changes"].append(
                {
                    "field_path": "settings.tools.enabled_mode",
                    "kind": "made_explicit",
                    "to": legacy.tools.enabled_mode,
                }
            )
        for key, value in list(doc["settings"]["runtime"].items()):
            bounds = RANGES.get("runtime." + key)
            if bounds and isinstance(value, (int, float)):
                lo, hi = bounds
                adjusted = max(lo, value) if hi is None else min(hi, max(lo, value))
                if adjusted != value:
                    report["changes"].append(
                        {
                            "field_path": "settings.runtime." + key,
                            "from": value,
                            "to": adjusted,
                            "kind": "clamped",
                        }
                    )
                    doc["settings"]["runtime"][key] = adjusted
        raw_providers = {p.get("id"): p for p in raw.get("providers", [])}
        for pid, provider in legacy.providers.items():
            original_provider = raw_providers[pid]
            values = asdict(provider)
            request = {
                k: values[k] for k in PARAMETER_TYPES if k in original_provider and k in values
            }
            request["style_profile"] = str(original_provider.get("style_profile", "")).strip()
            request["style_overrides"] = str(original_provider.get("style_overrides", "")).strip()
            # Frozen loader stamps global retry policy; explicit legacy provider keys were inert.
            for key in ("retry_max_attempts", "retry_base_delay", "retry_jitter"):
                request.pop(key, None)
                if key in original_provider:
                    report["warnings"].append(
                        {
                            "field_path": f"providers.{pid}.{key}",
                            "code": "legacy_inert_override_removed",
                        }
                    )
            for key, value in list(request.items()):
                bounds = RANGES.get(key)
                if value is not None and bounds and isinstance(value, (int, float)):
                    lo, hi = bounds
                    request[key] = max(lo, value) if hi is None else min(hi, max(lo, value))
            for key in PARAMETER_TYPES:
                if key in original_provider and original_provider[key] != request.get(key):
                    report["changes"].append(
                        {
                            "field_path": f"providers.{pid}.parameters.{key}",
                            "from": original_provider[key],
                            "to": request.get(key),
                            "kind": "normalized",
                        }
                    )
            known = set(PARAMETER_TYPES) | {
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
                "models",
                "aliases",
                "non_vision_models",
                "model_context_windows",
            }
            for key in original_provider.keys() - known:
                report["warnings"].append(
                    {"field_path": f"providers.{pid}.{key}", "code": "unrecognized_legacy_field"}
                )
            doc["providers"].append(
                {
                    "id": pid,
                    "protocol": provider.protocol,
                    "base_url": provider.base_url,
                    "api_key_env": provider.api_key_env,
                    "default_model": provider.default_model,
                    "enabled": provider.enabled,
                    "headers": provider.headers,
                    "fallback_urls": provider.fallback_urls,
                    "proxy": provider.proxy,
                    "auth_method": provider.auth_method,
                    "parameters": request,
                    "models": [
                        {
                            "model": m,
                            "enabled": True,
                            "vision": m not in provider.non_vision_models,
                            "context_window": provider.model_context_windows.get(m),
                            "parameters": {},
                        }
                        for m in provider.models
                    ],
                    "aliases": [{"alias": a, "model": m} for a, m in provider.aliases.items()],
                }
            )
        for key, rates in legacy.pricing.items():
            doc["pricing"].append({"provider_id": None, "model": key, **asdict(rates)})
            if "/" in key and key.split("/", 1)[0] in raw_providers:
                provider_id, model = key.split("/", 1)
                doc["pricing"].append({"provider_id": provider_id, "model": model, **asdict(rates)})
                report["changes"].append(
                    {
                        "field_path": "pricing." + key,
                        "kind": "qualified_and_response_fallback_preserved",
                    }
                )
        report["source_counts"] = {
            "providers": len(raw_providers),
            "models": sum(len(p.models) for p in legacy.providers.values()),
            "pricing": len(legacy.pricing),
            "mcp_servers": len(legacy.mcp.servers),
        }
        for name in ROUTES:
            for entry in getattr(legacy, name).model_cascade:
                if entry == "@default":
                    doc["routes"][name].append(entry)
                elif "/" in entry:
                    pid, model = entry.split("/", 1)
                    if not model and pid in legacy.providers:
                        model = legacy.providers[pid].default_model
                    doc["routes"][name].append({"provider_id": pid, "model": model})
                elif entry in legacy.providers:
                    doc["routes"][name].append(
                        {"provider_id": entry, "model": legacy.providers[entry].default_model}
                    )
                else:
                    raise ConfigError(
                        "invalid_legacy_reference", "级联引用无法转换", "routes." + name
                    )
        if "agent_delivery_enabled" in raw.get("runtime", {}):
            report["changes"].append(
                {
                    "field_path": "runtime.agent_delivery_enabled",
                    "kind": "mapped_to_delivery_domains",
                }
            )
        for name in ROUTES:
            known = set(doc["settings"][name]) | {"model_cascade"}
            for key in raw.get(name, {}):
                if key not in known:
                    report["changes"].append({"field_path": name + "." + key, "kind": "removed"})
        if set(raw_providers) != set(legacy.providers):
            raise ConfigError("invalid_legacy_provider", "旧解析器跳过了渠道，请先修复迁移输入")
        # Complete structural validation before external assets are materialized.
        doc = validate_document(doc)
        for section, values in doc["settings"].items():
            source = raw.get(section, {})
            if section in ("auto_search", "quick_judge"):
                source = raw.get("triggers", {}).get(section, {})
            for key, value in values.items():
                if key in source and source[key] != value:
                    report["changes"].append(
                        {
                            "field_path": f"settings.{section}.{key}",
                            "from": source[key],
                            "to": value,
                            "kind": "normalized",
                        }
                    )
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ConfigError("migration_source_changed", "迁移输入已变化，请重新执行迁移")
        _prepare_assets(path, raw, report, backup)
        durable_write(
            backup / "report.json",
            (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode(),
        )
        return doc, report
