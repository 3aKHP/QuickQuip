from __future__ import annotations

import logging
import os

from quickquip.app.message_pipeline import (
    llm_service,
    save_all,
    RULE_SWITCH_PATH,
    rule_switch,
    daily_enabled_groups,
    daily_briefing_enabled_groups,
)
from quickquip.tieba.service import tieba_service

logger = logging.getLogger(__name__)

# H1: 记录各状态文件上次已知的 mtime，用于检测 web-admin 的外部写入
_watched: dict[str, float] = {}


def _init_mtimes() -> None:
    """启动时记录初始 mtime，避免首次轮询误判为变化。"""
    for path in (
        RULE_SWITCH_PATH,
        daily_enabled_groups.path,
        daily_briefing_enabled_groups.path,
    ):
        try:
            _watched[str(path)] = os.stat(path).st_mtime
        except OSError:
            _watched[str(path)] = 0.0


def _reload_if_changed() -> None:
    """H1: 检测状态文件是否被 web-admin 进程修改，有变化则 reload。"""
    checks = [
        (RULE_SWITCH_PATH, lambda: rule_switch.load(RULE_SWITCH_PATH)),
        (daily_enabled_groups.path, daily_enabled_groups.load),
        (daily_briefing_enabled_groups.path, daily_briefing_enabled_groups.load),
    ]
    for path, reload_fn in checks:
        key = str(path)
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            continue
        if mtime != _watched.get(key, 0.0):
            _watched[key] = mtime
            try:
                reload_fn()
                logger.info("reloaded %s after external change", path)
            except Exception:
                logger.warning("failed to reload %s", path, exc_info=True)


def register_lifecycle(driver) -> None:
    @driver.on_startup
    async def _startup_llm_runtime():
        await llm_service.startup(background=True)
        await tieba_service.startup()
        _init_mtimes()

    @driver.on_shutdown
    async def _save_on_shutdown():
        await tieba_service.shutdown()
        await llm_service.shutdown()
        save_all()

    try:
        from nonebot_plugin_apscheduler import scheduler

        scheduler.add_job(
            save_all,
            "interval",
            minutes=5,
            id="persistence_auto_save",
            replace_existing=True,
        )
        scheduler.add_job(
            _reload_if_changed,
            "interval",
            seconds=30,
            id="web_admin_state_sync",
            replace_existing=True,
        )
    except ModuleNotFoundError:
        pass
