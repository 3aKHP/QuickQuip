from __future__ import annotations

from datetime import time

from quickquip.chat.timezones import (
    circular_diff_minutes,
    find_best_timezones,
    format_city_zh,
    format_location_zh,
)


def test_format_location_and_city_zh():
    assert format_location_zh("Asia/Shanghai") == "亚洲/上海"
    assert format_location_zh("Atlantic/Cape_Verde") == "大西洋/佛得角"
    assert format_city_zh("Asia/Shanghai") == "上海"
    assert format_city_zh("Atlantic/Cape_Verde") == "佛得角"


def test_find_best_timezones_shape_and_order(frozen_now):
    candidates = find_best_timezones(frozen_now, time(7, 30), limit=3)
    assert len(candidates) == 3
    for item in candidates:
        assert {"location_zh", "city_zh", "local_dt", "diff"} <= item.keys()
    assert candidates[0]["diff"] <= candidates[1]["diff"] <= candidates[2]["diff"]
    assert len({item["city_zh"] for item in candidates}) == 3


def test_circular_diff_minutes():
    assert circular_diff_minutes(0, 0) == 0
    assert circular_diff_minutes(100, 200) == 100
    # 跨午夜
    assert circular_diff_minutes(10, 1430) == 20
