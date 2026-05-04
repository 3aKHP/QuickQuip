from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Festival:
    name: str
    month: int
    day: int
    calendar: str  # "solar" 公历 / "lunar" 农历
    greeting: str


_FESTIVALS: list[Festival] = [
    Festival(name="元旦", month=1, day=1, calendar="solar", greeting="新年快乐！愿新的一年大家万事顺遂。"),
    Festival(name="春节", month=1, day=1, calendar="lunar", greeting="新春快乐！给大家拜年啦，祝大家身体健康、阖家幸福！"),
    Festival(name="元宵节", month=1, day=15, calendar="lunar", greeting="元宵节快乐！记得吃汤圆哦～"),
    Festival(name="端午节", month=5, day=5, calendar="lunar", greeting="端午安康！今天吃粽子了吗？"),
    Festival(name="中秋节", month=8, day=15, calendar="lunar", greeting="中秋快乐！月圆人团圆，别忘了吃月饼～"),
]

_active_festival: Festival | None = None
_checked_date: date | None = None

_PERSONA_APPENDIX: dict[str, str] = {
    "元旦": "今天是元旦，新年的第一天。请在回复中自然地融入新年的祝福和积极向上的语气，但不要生硬。",
    "春节": "今天是春节。请在回复中自然地融入新春祝福的语气，可以适当使用拜年用语，但不要生硬。",
    "元宵节": "今天是元宵节。可以在回复中自然地提到元宵、汤圆、团圆等元素，语气温馨一些。",
    "端午节": "今天是端午节。可以在回复中自然地提到粽子、龙舟等元素，语气可以适当体现节日氛围。",
    "中秋节": "今天是中秋节。可以在回复中自然地提到月亮、月饼、团圆等元素，语气温馨一些。",
    "除夕": "今天是除夕，辞旧迎新之际。请在回复中自然地融入辞旧迎新的氛围，可以祝福大家新年进步，但不要生硬。",
}


def _make_chuxi_festival() -> Festival:
    """Return a Festival instance for 除夕."""
    return Festival(
        name="除夕",
        month=12,
        day=30,
        calendar="lunar",
        greeting="除夕快乐！辞旧迎新，祝大家阖家团圆、万事如意！",
    )


def _is_chuxi(today: date) -> Festival | None:
    """Check if today is 除夕 (Lunar New Year's Eve).

    除夕 is the day before 春节 (lunar 1/1). Check if tomorrow is 春节.
    """
    tomorrow = today + timedelta(days=1)
    try:
        from lunardate import LunarDate
        tomorrow_lunar = LunarDate.fromSolarDate(tomorrow.year, tomorrow.month, tomorrow.day)
    except Exception:
        return None
    if tomorrow_lunar.month == 1 and tomorrow_lunar.day == 1:
        return _make_chuxi_festival()
    return None


def check_today_festival(today: date | None = None) -> Festival | None:
    """Check if today is a festival, update _active_festival, and return it."""
    global _active_festival, _checked_date

    if today is None:
        today = date.today()
    _checked_date = today

    # 1) Solar calendar festivals
    for f in _FESTIVALS:
        if f.calendar == "solar" and f.month == today.month and f.day == today.day:
            _active_festival = f
            return f

    # 2) Lunar calendar festivals
    try:
        from lunardate import LunarDate
        lunar = LunarDate.fromSolarDate(today.year, today.month, today.day)
    except Exception:
        lunar = None

    if lunar is not None:
        for f in _FESTIVALS:
            if f.calendar == "lunar" and f.month == lunar.month and f.day == lunar.day:
                _active_festival = f
                return f

    # 3) 除夕 (special case — check if tomorrow is 春节)
    chuxi = _is_chuxi(today)
    if chuxi is not None:
        _active_festival = chuxi
        return chuxi

    _active_festival = None
    return None


def get_active_festival() -> Festival | None:
    """Return the currently active festival, or None.

    If _active_festival hasn't been set yet today (e.g. bot restarted after
    the 1 AM cron job), lazily check today's date.
    """
    global _active_festival, _checked_date
    today = date.today()
    if _checked_date != today:
        check_today_festival(today)
    return _active_festival


def get_festival_persona_appendix() -> str | None:
    """Return a short (2-3 sentences) festive persona instruction for the active festival.

    Returns None when no festival is active.
    """
    f = get_active_festival()
    if f is None:
        return None
    return _PERSONA_APPENDIX.get(f.name)


def get_festival_greeting() -> str | None:
    """Return the greeting text for the active festival, or None."""
    f = get_active_festival()
    if f is None:
        return None
    return f.greeting
