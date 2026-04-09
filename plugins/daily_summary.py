from quickquip.app.message_pipeline import (
    daily_collector as collector,
    daily_enabled_groups as enabled_groups,
    daily_store as store,
    record_group_message,
)
from quickquip.adapters.nonebot.daily_summary_plugin import setup

__all__ = [
    "collector",
    "enabled_groups",
    "record_group_message",
    "setup",
    "store",
]
