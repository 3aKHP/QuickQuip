"""一次性任务测试的钉死 cron 生成器：相对后端校验口径（Asia/Shanghai、按"今年对应时刻"判定）永不跨期。

后端 ``validate_one_off_schedule`` 按北京时区取当前时间、用当前年份构造钉死月/日对应的时刻，
因此这里一律按北京时区取 now，且保证钉死的月/日落在今年——否则 12/31 与 1/1 会变成一年一度的测试炸弹。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from quickquip.common.constants import BEIJING_TIMEZONE


def _now() -> datetime:
    return datetime.now(ZoneInfo(BEIJING_TIMEZONE))


def future_one_shot_cron() -> str:
    """钉死分/时/日/月的一次性 cron，今年对应时刻必在未来。

    12 月 31 日跨年时退化为当天 23:59；年末最后一分钟的极端边界退化为不钉日/月
    （校验只要求存在未来触发，不影响调用方的其余断言）。
    """
    now = _now()
    future = now + timedelta(days=1)
    if future.year != now.year:
        future = now.replace(hour=23, minute=59, second=0, microsecond=0)
        if future <= now:
            later = now + timedelta(minutes=2)
            return f"{later.minute} {later.hour} * * *"
    return f"{future.minute} {future.hour} {future.day} {future.month} *"


def past_one_shot_cron() -> str:
    """钉死分/时/日/月的一次性 cron，今年对应时刻必已过。

    1 月 1 日跨年时退化为当天 00:00（必已过）。
    """
    now = _now()
    past = now - timedelta(days=1)
    if past.year != now.year:
        past = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return f"{past.minute} {past.hour} {past.day} {past.month} *"
