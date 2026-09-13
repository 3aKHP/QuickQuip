"""唤醒配置域：TOML 持久化形状、按群解析与配置单例。"""
from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from quickquip.common.paths import CONFIG_AWAKENING_TOML

logger = logging.getLogger(__name__)


def _filter_config_fields(data: dict[str, Any], valid: set[str]) -> dict[str, Any]:
    """按字段名集过滤未知键并清洗 ``interest_topics``（两个 from_dict 共用）。

    None 值视同未设置（保持 dataclass 默认/覆盖语义）；非 list 的
    interest_topics 原样透传（沿用拆分前行为）。
    """
    filtered: dict[str, Any] = {}
    for key, value in data.items():
        if key not in valid or value is None:
            continue
        if key == "interest_topics" and isinstance(value, list):
            filtered[key] = [str(item).strip() for item in value if str(item).strip()]
        else:
            filtered[key] = value
    return filtered


@dataclass(slots=True)
class AwakeningDefaults:
    extend_duration: int = 0
    fallback_probability: float = 0.0
    boredom_silence_seconds: int = 0
    boredom_probability: float = 0.0
    boredom_check_interval: int = 300
    # 全局 scheduler 扫描周期（秒）。None = 未设置，回退到 boredom_check_interval；
    # boredom_check_interval 固定为群级成功唤醒冷却时间。
    boredom_scan_interval: int | None = None
    boredom_dnd_start: str = ""
    boredom_dnd_end: str = ""
    interest_topics: list[str] = field(default_factory=list)
    relevance_threshold: float = 1.0
    qa_threshold: float = 1.0

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AwakeningDefaults:
        if not data:
            return cls()
        return cls(**_filter_config_fields(data, {f.name for f in fields(cls)}))


@dataclass(slots=True)
class AwakeningGroupOverride:
    group_id: str = ""
    extend_duration: int | None = None
    fallback_probability: float | None = None
    boredom_silence_seconds: int | None = None
    boredom_probability: float | None = None
    boredom_check_interval: int | None = None
    boredom_dnd_start: str | None = None
    boredom_dnd_end: str | None = None
    interest_topics: list[str] | None = None
    relevance_threshold: float | None = None
    qa_threshold: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AwakeningGroupOverride | None:
        if not data:
            return None
        group_id = str(data.get("group_id", "")).strip()
        if not group_id:
            return None
        valid = {f.name for f in fields(cls)} - {"group_id"}
        return cls(group_id=group_id, **_filter_config_fields(data, valid))


@dataclass(slots=True)
class ResolvedAwakeningSettings:
    extend_duration: int = 0
    fallback_probability: float = 0.0
    boredom_silence_seconds: int = 0
    boredom_probability: float = 0.0
    boredom_check_interval: int = 300
    boredom_dnd_start: str = ""
    boredom_dnd_end: str = ""
    interest_topics: list[str] = field(default_factory=list)
    relevance_threshold: float = 1.0
    qa_threshold: float = 1.0


@dataclass(slots=True)
class AwakeningConfig:
    defaults: AwakeningDefaults = field(default_factory=AwakeningDefaults)
    group_overrides: dict[str, AwakeningGroupOverride] = field(default_factory=dict)
    load_error: str | None = None
    source_path: Path | None = None

    def resolve_group(self, group_id: int | str) -> ResolvedAwakeningSettings:
        """按 ``ResolvedAwakeningSettings`` 字段集合并 defaults 与群覆盖。

        驱动字段集 = resolved 的 dataclass 字段：``boredom_scan_interval``
        天然排除在外（它只服务 scheduler 扫描周期，经
        ``effective_boredom_scan_interval`` 消费，不进群级 resolved 输出）。
        覆盖值非 None 优先；``interest_topics`` 输出恒为新列表，避免与
        defaults 共享可变引用。
        """
        override = self.group_overrides.get(str(group_id))
        d = self.defaults
        values: dict[str, Any] = {}
        for f in fields(ResolvedAwakeningSettings):
            value = getattr(d, f.name)
            if override is not None:
                override_value = getattr(override, f.name)
                if override_value is not None:
                    value = override_value
            if f.name == "interest_topics":
                value = list(value)
            values[f.name] = value
        return ResolvedAwakeningSettings(**values)


def load_awakening_config(path: str | Path) -> AwakeningConfig:
    config_path = Path(path)
    if not config_path.exists():
        return AwakeningConfig(source_path=config_path)

    try:
        with config_path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return AwakeningConfig(load_error=f"无法解析 {config_path}：{exc}", source_path=config_path)

    raw = data.get("awakening", data)
    defaults = AwakeningDefaults.from_dict(raw.get("defaults"))

    overrides: dict[str, AwakeningGroupOverride] = {}
    for entry in raw.get("group_overrides", []):
        if not isinstance(entry, dict):
            continue
        ov = AwakeningGroupOverride.from_dict(entry)
        if ov is not None:
            overrides[ov.group_id] = ov

    return AwakeningConfig(
        defaults=defaults,
        group_overrides=overrides,
        source_path=config_path,
    )


_config: AwakeningConfig = load_awakening_config(CONFIG_AWAKENING_TOML)


def get_config() -> AwakeningConfig:
    return _config


def reload_config(path: str | Path | None = None) -> None:
    global _config
    _config = load_awakening_config(path or CONFIG_AWAKENING_TOML)


def effective_boredom_scan_interval(config: AwakeningConfig | None = None) -> int:
    """APScheduler 扫描周期：新字段优先；未设置时回退旧配置的
    ``defaults.boredom_check_interval``（兼容尚未写新键的私有部署）。"""
    cfg = config if config is not None else _config
    if cfg.defaults.boredom_scan_interval is not None and cfg.defaults.boredom_scan_interval > 0:
        return cfg.defaults.boredom_scan_interval
    interval = cfg.defaults.boredom_check_interval
    return interval if interval > 0 else 300
