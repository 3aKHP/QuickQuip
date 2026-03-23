import re
from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones

from quickquip.chat.config import REGION_ZH, TZ_PART_ZH


def circular_diff_minutes(a: int, b: int) -> int:
    return abs((a - b + 720) % 1440 - 720)


def format_location_zh(tz_name: str) -> str:
    parts = tz_name.split("/")
    region = REGION_ZH.get(parts[0], parts[0])
    local_parts = [TZ_PART_ZH.get(part, part.replace("_", "·")) for part in parts[1:]]
    if not local_parts:
        return region
    return f"{region}/{'/'.join(local_parts)}"


def format_city_zh(tz_name: str) -> str:
    parts = tz_name.split("/")
    if len(parts) <= 1:
        return REGION_ZH.get(parts[0], parts[0])

    local_parts = [TZ_PART_ZH.get(part, part.replace("_", "·")) for part in parts[1:]]
    return "/".join(local_parts)


def find_best_timezones(now_cst: datetime, target, limit: int = 3):
    target_min = target.hour * 60 + target.minute
    candidates = []

    for tz_name in available_timezones():
        if tz_name.startswith(("Etc/", "GMT", "UTC", "Factory", "SystemV/")):
            continue
        if "/" not in tz_name:
            continue

        local_dt = now_cst.astimezone(ZoneInfo(tz_name))
        local_min = local_dt.hour * 60 + local_dt.minute
        diff = circular_diff_minutes(local_min, target_min)

        city_zh = format_city_zh(tz_name)
        if re.search(r"[a-zA-Z]", city_zh):
            continue

        candidates.append(
            {
                "tz_name": tz_name,
                "location_zh": format_location_zh(tz_name),
                "city_zh": city_zh,
                "local_dt": local_dt,
                "diff": diff,
            }
        )

    candidates.sort(key=lambda item: (item["diff"], item["tz_name"]))

    unique_candidates = []
    seen_cities = set()
    for item in candidates:
        city_zh = item["city_zh"]
        if city_zh in seen_cities:
            continue
        seen_cities.add(city_zh)
        unique_candidates.append(item)
        if len(unique_candidates) >= limit:
            break

    return unique_candidates
