from __future__ import annotations

import json
import re
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from filelock import FileLock
from pydantic import BaseModel
import tomllib

from quickquip.common.paths import RULE_SWITCH_JSON_PATH as RULE_SWITCH_PATH
from quickquip.app.web.action_queue import action_queue
from quickquip.app.web.audit import audit_logger
from quickquip.chat.awakening import (
    AwakeningConfig,
    AwakeningGroupOverride,
    CONFIG_AWAKENING_TOML,
    effective_boredom_scan_interval,
    get_config,
    load_awakening_config,
    reload_config,
)

router = APIRouter()

_GROUP_ID_RE = re.compile(r"^\d{5,12}$")
_BOREDOM_GROUPS_PATH = Path("data/awakening_boredom_groups.json")
_CONFIG_PATH = CONFIG_AWAKENING_TOML
_AWAKENING_RULES = [
    ("awakening_extend", "唤醒延长"),
    ("awakening_interest", "兴趣话题"),
    ("awakening_relevance", "相关性唤醒"),
    ("awakening_qa", "答疑唤醒"),
    ("awakening_boredom", "无聊唤醒"),
    ("awakening_fallback", "兜底概率"),
]
_VALID_RULES = {name for name, _label in _AWAKENING_RULES}
_OVERRIDE_FIELDS = [
    "extend_duration",
    "fallback_probability",
    "boredom_silence_seconds",
    "boredom_probability",
    "boredom_check_interval",
    "boredom_dnd_start",
    "boredom_dnd_end",
    "relevance_threshold",
    "qa_threshold",
]
_ALL_GROUP_OVERRIDE_FIELDS = [f.name for f in fields(AwakeningGroupOverride) if f.name != "group_id"]
_TIME_RE = re.compile(r"^(?:|(?:[01]\d|2[0-3]):[0-5]\d)$")


class ToggleBody(BaseModel):
    enabled: bool


class AwakeningSettingsBody(BaseModel):
    # Optional fields use model_dump(exclude_unset=True) in the route.
    # Sending null clears a group override; omitting leaves it unchanged.
    extend_duration: int | None = None
    fallback_probability: float | None = None
    boredom_silence_seconds: int | None = None
    boredom_probability: float | None = None
    boredom_check_interval: int | None = None
    boredom_dnd_start: str | None = None
    boredom_dnd_end: str | None = None
    relevance_threshold: float | None = None
    qa_threshold: float | None = None


def _validate_group_id(group_id: str) -> None:
    if not _GROUP_ID_RE.match(group_id):
        raise HTTPException(status_code=422, detail="group_id must be 5-12 digits")


def _validate_settings_payload(payload: dict[str, Any]) -> None:
    for key, value in payload.items():
        if key not in _OVERRIDE_FIELDS:
            raise HTTPException(status_code=422, detail=f"unsupported awakening setting: {key}")
        if value is None:
            continue
        if key in {"extend_duration", "boredom_silence_seconds", "boredom_check_interval"}:
            if type(value) is not int or value < 0 or value > 604800:
                raise HTTPException(status_code=422, detail=f"{key} must be an integer between 0 and 604800")
        elif key in {"fallback_probability", "boredom_probability", "relevance_threshold", "qa_threshold"}:
            if type(value) not in {int, float} or value < 0 or value > 1:
                raise HTTPException(status_code=422, detail=f"{key} must be between 0 and 1")
        elif key in {"boredom_dnd_start", "boredom_dnd_end"}:
            if not isinstance(value, str) or not _TIME_RE.match(value.strip()):
                raise HTTPException(status_code=422, detail=f"{key} must be empty or HH:MM")
            payload[key] = value.strip()


def _toml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return _toml_quote(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_quote(str(item)) for item in value) + "]"
    raise TypeError(f"unsupported TOML value: {value!r}")


def _lock_for(path: Path) -> FileLock:
    path.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(str(path) + ".lock")


def _render_awakening_config(cfg: AwakeningConfig) -> str:
    defaults = asdict(cfg.defaults)
    lines = [
        "# Managed by QuickQuip Web Admin.",
        "",
        "[awakening.defaults]",
    ]
    for field_name in [
        "extend_duration",
        "fallback_probability",
        "boredom_silence_seconds",
        "boredom_probability",
        "boredom_scan_interval",
        "boredom_check_interval",
        "boredom_dnd_start",
        "boredom_dnd_end",
        "interest_topics",
        "relevance_threshold",
        "qa_threshold",
    ]:
        value = defaults[field_name]
        if field_name == "boredom_scan_interval" and value is None:
            # 未设置即不写键：保持「回退 boredom_check_interval」的动态语义，
            # 不把回退值物化进托管文件
            continue
        lines.append(f"{field_name} = {_toml_value(value)}")

    for group_id in sorted(cfg.group_overrides):
        override = cfg.group_overrides[group_id]
        lines.extend(["", "[[awakening.group_overrides]]", f"group_id = {_toml_quote(group_id)}"])
        values = asdict(override)
        for field_name in _ALL_GROUP_OVERRIDE_FIELDS:
            value = values[field_name]
            if value is not None:
                lines.append(f"{field_name} = {_toml_value(value)}")

    content = "\n".join(lines).rstrip() + "\n"
    tomllib.loads(content)
    return content


def _write_awakening_config_unlocked(cfg: AwakeningConfig, target_path: Path) -> None:
    content = _render_awakening_config(cfg)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = target_path.with_suffix(target_path.suffix + ".tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(target_path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _write_awakening_config(cfg: AwakeningConfig, path: Path | None = None) -> None:
    target_path = path or _CONFIG_PATH
    with _lock_for(target_path):
        _write_awakening_config_unlocked(cfg, target_path)


def _apply_group_settings(group_id: str, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    target_path = _CONFIG_PATH
    with _lock_for(target_path):
        cfg = load_awakening_config(target_path)
        if cfg.load_error:
            raise HTTPException(status_code=409, detail=f"awakening.toml load error: {cfg.load_error}")
        before = asdict(cfg.group_overrides[group_id]) if group_id in cfg.group_overrides else None
        existing = cfg.group_overrides.get(group_id)
        override = AwakeningGroupOverride(**asdict(existing)) if existing is not None else AwakeningGroupOverride(group_id=group_id)
        for key, value in payload.items():
            setattr(override, key, value)
        next_overrides = dict(cfg.group_overrides)
        values = asdict(override)
        has_any_override = any(values[field_name] is not None for field_name in _ALL_GROUP_OVERRIDE_FIELDS)
        if has_any_override:
            next_overrides[group_id] = override
        else:
            next_overrides.pop(group_id, None)
        next_cfg = AwakeningConfig(defaults=cfg.defaults, group_overrides=next_overrides, source_path=cfg.source_path)
        _write_awakening_config_unlocked(next_cfg, target_path)
        reload_config(target_path)
        after_override = get_config().group_overrides.get(group_id)
        after = asdict(after_override) if after_override is not None else None
    return before or {}, after or {}


def _load_boredom_groups() -> set[str]:
    if not _BOREDOM_GROUPS_PATH.exists():
        return set()
    try:
        data = json.loads(_BOREDOM_GROUPS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    groups = data.get("enabled", [])
    return {str(g) for g in groups if _GROUP_ID_RE.match(str(g))}


def _save_boredom_groups(groups: set[str]) -> None:
    _BOREDOM_GROUPS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _BOREDOM_GROUPS_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"enabled": sorted(groups)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(_BOREDOM_GROUPS_PATH)


def _known_group_ids() -> list[str]:
    from quickquip.app.message_pipeline import stats_tracker

    groups = set(stats_tracker.to_dict().keys())
    groups.update(get_config().group_overrides.keys())
    groups.update(_load_boredom_groups())
    return sorted(g for g in groups if _GROUP_ID_RE.match(str(g)))


def _format_group(group_id: str) -> dict:
    from quickquip.app.message_pipeline import rule_switch

    cfg = get_config()
    settings = cfg.resolve_group(group_id)
    boredom_groups = _load_boredom_groups()
    override = cfg.group_overrides.get(group_id)
    return {
        "group_id": group_id,
        "rules": [
            {
                "name": rule_name,
                "label": label,
                "enabled": rule_switch.is_enabled(group_id, rule_name),
            }
            for rule_name, label in _AWAKENING_RULES
        ],
        "settings": asdict(settings),
        "override": asdict(override) if override is not None else {"group_id": group_id, **{field_name: None for field_name in _ALL_GROUP_OVERRIDE_FIELDS}},
        "has_override": group_id in cfg.group_overrides,
        "boredom_opt_in": group_id in boredom_groups,
    }


@router.get("/awakening")
def list_awakening():
    cfg = get_config()
    return {
        "load_error": cfg.load_error,
        "defaults": asdict(cfg.defaults),
        # 回退规则的单一来源：前端只消费生效值，不重复实现回退链
        "effective_boredom_scan_interval": effective_boredom_scan_interval(cfg),
        "rules": [{"name": name, "label": label} for name, label in _AWAKENING_RULES],
        "groups": [_format_group(group_id) for group_id in _known_group_ids()],
    }


@router.get("/awakening/{group_id}")
def get_awakening_group(group_id: str):
    _validate_group_id(group_id)
    return _format_group(group_id)


@router.post("/awakening/{group_id}/rules/{rule_name}")
def set_awakening_rule(group_id: str, rule_name: str, body: ToggleBody, request: Request):
    _validate_group_id(group_id)
    if rule_name not in _VALID_RULES:
        raise HTTPException(status_code=404, detail="unknown awakening rule")
    from quickquip.app.message_pipeline import rule_switch

    old_enabled = rule_switch.is_enabled(group_id, rule_name)
    if body.enabled:
        rule_switch.enable(group_id, rule_name)
    else:
        rule_switch.disable(group_id, rule_name)
    rule_switch.save(RULE_SWITCH_PATH)
    audit_logger.log(
        request,
        action="toggle",
        target_type="awakening_rule",
        target_id=f"{group_id}:{rule_name}",
        summary_before={"enabled": old_enabled},
        summary_after={"enabled": body.enabled},
    )
    return {"ok": True}


@router.post("/awakening/{group_id}/boredom")
def set_boredom_opt_in(group_id: str, body: ToggleBody, request: Request):
    _validate_group_id(group_id)
    with _lock_for(_BOREDOM_GROUPS_PATH):
        groups = _load_boredom_groups()
        old_enabled = group_id in groups
        if body.enabled:
            groups.add(group_id)
        else:
            groups.discard(group_id)
        _save_boredom_groups(groups)
    audit_logger.log(
        request,
        action="toggle",
        target_type="awakening_boredom_group",
        target_id=group_id,
        summary_before={"enabled": old_enabled},
        summary_after={"enabled": body.enabled},
    )
    return {"ok": True}


@router.put("/awakening/{group_id}/settings")
def set_awakening_settings(group_id: str, body: AwakeningSettingsBody, request: Request):
    _validate_group_id(group_id)
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="no fields to update")
    _validate_settings_payload(payload)
    before, after = _apply_group_settings(group_id, payload)
    action = action_queue.enqueue("awakening_reload")
    audit_logger.log(
        request,
        action="update",
        target_type="awakening_settings",
        target_id=group_id,
        summary_before=before,
        summary_after={"fields": list(payload.keys()), "override": after, "action_id": action["id"]},
    )
    return {"ok": True, "queued": True, "action": action, "group": _format_group(group_id)}
