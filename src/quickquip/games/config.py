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
    unsubscribe_gold: int = 500

    # Per-group RPM limits (requests per minute window)
    glue_rpm_limit: int = 30
    fence_rpm_limit: int = 20
    rpm_window_seconds: int = 60

    # Text TOML paths — empty means use built-in defaults
    niuniu_text_path: str = ""
    niuniu_safe_text_path: str = ""
    decay_rate_high: float = 0.01
    decay_rate_normal: float = 0.005

    # Growth formula tuning
    glue_growth_scale: float = 500.0

    # Gluing event tuning
    glue_lucky_coefficient: float = 1.8
    glue_special_coefficient: float = 1.3
    glue_shrinkage_effect: float = 0.5
    glue_nightmare_effect: float = 0.7
    glue_arrested_duration: int = 60
    glue_blessing_min: float = 5.0
    glue_blessing_max: float = 18.0
    glue_gambler_min: float = 4.0
    glue_gambler_max: float = 14.0
    glue_zen_min: float = 1.0
    glue_zen_max: float = 4.0
    glue_frenzy_min: float = 3.0
    glue_frenzy_max: float = 10.0

    # Fencing event tuning
    fence_critical_multiplier: float = 1.8
    fence_glancing_multiplier: float = 0.4
    fence_dominate_multiplier: float = 3.0
    fence_dominate_sever_chance: float = 0.4
    fence_dominate_threshold: float = 50.0
    fence_devour_steal_ratio: float = 0.3
    fence_devour_threshold: float = 50.0
    fence_draw_min: float = 0.5
    fence_draw_max: float = 2.0

    # No-niuniu target tuning
    fence_self_hurt_min: float = 0.5
    fence_self_hurt_max: float = 2.5

    # Bot fencing tuning
    fence_bot_phantom_min: float = 5.0
    fence_bot_phantom_max: float = 80.0

    # Daily luck tuning — log10-symmetric: lg(x) ~ N(0, σ)
    # σ=1 → ±1σ = [0.1, 10] (one order of magnitude), ±2σ = [0.01, 100] (clamp bounds)
    luck_sigma: float = 1.0

    # Daily fence luck tuning — same distribution, separate daily roll
    fence_luck_sigma: float = 1.0

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
