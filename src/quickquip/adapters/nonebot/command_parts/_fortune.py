from __future__ import annotations

import hashlib
from datetime import date


_FORTUNES = [
    ("大吉", "财运亨通，诸事大顺，今日宜出行、宜交友"),
    ("吉", "今日顺遂，保持当下状态即可"),
    ("中吉", "稳中求进，努力终有回报"),
    ("小吉", "小有收获，量力而行，不必强求"),
    ("末吉", "平稳即福，顺势而为，随心所欲"),
    ("平", "波澜不惊，平常心是最贵的"),
    ("小凶", "遇事三思而后行，不宜冒进"),
    ("凶", "今日多有阻碍，静待时机，勿急于求成"),
]
_NUMBER_EMOJIS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣")


def _daily_fortune(user_id: int | str) -> tuple[str, str]:
    h = int(hashlib.md5(f"{user_id}:{date.today().isoformat()}".encode()).hexdigest(), 16)
    return _FORTUNES[h % len(_FORTUNES)]


def _evaluate_luck(value: float) -> str:
    if value < 0.2:
        return "大凶"
    elif value < 0.5:
        return "凶"
    elif value < 0.8:
        return "平"
    elif value < 1.2:
        return "吉"
    elif value < 3.0:
        return "大吉"
    else:
        return "神运"


def _luck_lookup(value: float, table: list[dict]) -> str:
    """Find the first luck tip whose range contains *value*."""
    for entry in table:
        if entry["min"] <= value < entry["max"]:
            return entry["text"]
    return table[-1]["text"] if table else "运势未知…"


def _glue_luck_tips(value: float, text=None) -> str:
    if text is not None and text.luck_glue:
        return _luck_lookup(value, text.luck_glue)
    return _luck_lookup(value, _DEFAULT_GLUE_LUCK)


def _fence_luck_tips(value: float, text=None) -> str:
    if text is not None and text.luck_fence:
        return _luck_lookup(value, text.luck_fence)
    return _luck_lookup(value, _DEFAULT_FENCE_LUCK)


# Built-in fallbacks used when no text object is available
_DEFAULT_GLUE_LUCK: list[dict] = [
    {"min": 0.0, "max": 0.2, "text": "今日不宜打胶，牛牛极易萎缩…"},
    {"min": 0.2, "max": 0.5, "text": "运势低迷，打胶效果减半，小心凹进去！"},
    {"min": 0.5, "max": 0.8, "text": "运势平平，平常心对待即可~"},
    {"min": 0.8, "max": 1.2, "text": "运势尚可，正常发挥！"},
    {"min": 1.2, "max": 3.0, "text": "运势旺盛，打胶事半功倍！"},
    {"min": 3.0, "max": 999.0, "text": "运势如虹！今日打胶效果极佳，冲！！"},
]

_DEFAULT_FENCE_LUCK: list[dict] = [
    {"min": 0.0, "max": 0.2, "text": "今日击剑大凶，极易翻车…建议避战！"},
    {"min": 0.2, "max": 0.5, "text": "击剑运势不佳，谨慎出手！"},
    {"min": 0.5, "max": 0.8, "text": "运势中规中矩，可战可不战~"},
    {"min": 0.8, "max": 1.2, "text": "运势良好，可放手一战！"},
    {"min": 1.2, "max": 3.0, "text": "运势高涨！今日击剑胜率大幅提升！"},
    {"min": 3.0, "max": 999.0, "text": "运势如神！今日击剑无往不利，战无不胜！！"},
]
