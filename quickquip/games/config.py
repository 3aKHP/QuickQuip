from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
import tomllib
from typing import Any


@dataclass(slots=True)
class EconomyConfig:
    """金币经济系统配置。"""

    sign_base_gold: int = 10
    sign_streak_bonus: int = 2
    sign_max_streak_bonus: int = 30
    affection_per_sign: int = 1

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> EconomyConfig:
        if not data:
            return cls()
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid and v is not None})


@dataclass(slots=True)
class NumberBombConfig:
    """数字炸弹配置。"""

    min_number: int = 1
    max_number: int = 1000
    timeout_seconds: int = 60

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> NumberBombConfig:
        if not data:
            return cls()
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid and v is not None})


@dataclass(slots=True)
class BlackjackConfig:
    """21 点配置。"""

    min_bet: int = 20
    max_players: int = 8
    timeout_seconds: int = 90
    dealer_stand_threshold: int = 17

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> BlackjackConfig:
        if not data:
            return cls()
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid and v is not None})


@dataclass(slots=True)
class RussianRouletteConfig:
    """俄罗斯轮盘配置。"""

    cylinder_slots: int = 7
    min_bet: int = 20
    timeout_seconds: int = 30

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> RussianRouletteConfig:
        if not data:
            return cls()
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid and v is not None})


@dataclass(slots=True)
class NiuNiuConfig:
    """牛牛大作战配置。"""

    fence_cooldown: int = 180
    fenced_protection: int = 300
    glue_cooldown: int = 180
    quick_glue_window: int = 240
    unsubscribe_gold: int = 500
    decay_rate_high: float = 0.03
    decay_rate_normal: float = 0.02
    decay_floor: int = -100

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> NiuNiuConfig:
        if not data:
            return cls()
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid and v is not None})


@dataclass(slots=True)
class GameConfig:
    """聚合所有游戏相关配置。"""

    economy: EconomyConfig = field(default_factory=EconomyConfig)
    number_bomb: NumberBombConfig = field(default_factory=NumberBombConfig)
    blackjack: BlackjackConfig = field(default_factory=BlackjackConfig)
    russian_roulette: RussianRouletteConfig = field(default_factory=RussianRouletteConfig)
    niuniu: NiuNiuConfig = field(default_factory=NiuNiuConfig)

    load_error: str | None = None
    source_path: Path | None = None

    @classmethod
    def defaults(cls) -> GameConfig:
        """Return a config with all defaults (no file loaded)."""
        return cls()


def load_games_config(path: str | Path) -> GameConfig:
    """Load game configuration from a TOML file.

    Missing file → all-defaults (no error).
    Malformed file → load_error set, all sections fall back to defaults.
    """
    config_path = Path(path)
    if not config_path.exists():
        return GameConfig(source_path=config_path)

    try:
        with config_path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return GameConfig(load_error=f"无法解析 {config_path}：{exc}", source_path=config_path)

    return GameConfig(
        economy=EconomyConfig.from_dict(data.get("economy")),
        number_bomb=NumberBombConfig.from_dict(data.get("number_bomb")),
        blackjack=BlackjackConfig.from_dict(data.get("blackjack")),
        russian_roulette=RussianRouletteConfig.from_dict(data.get("russian_roulette")),
        niuniu=NiuNiuConfig.from_dict(data.get("niuniu")),
        source_path=config_path,
    )
