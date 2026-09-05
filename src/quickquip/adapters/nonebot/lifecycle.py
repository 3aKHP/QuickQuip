from __future__ import annotations

import logging
import os

from quickquip.app.message_pipeline import (
    close_persistent_stores,
    get_llm_service,
    save_all,
    RULE_SWITCH_PATH,
    rule_switch,
    daily_enabled_groups,
    daily_briefing_enabled_groups,
    weekly_enabled_groups,
    monthly_enabled_groups,
    tieba_service,
)
from quickquip.adapters.nonebot.awakening_plugin import (
    boredom_enabled_groups,
    reload_awakening_and_reschedule,
    reload_boredom_groups,
)
from quickquip.adapters.nonebot.web_admin_actions import process_web_admin_actions
from quickquip.common.paths import CONFIG_AWAKENING_TOML

logger = logging.getLogger(__name__)

# H1: 记录各状态文件上次已知的 mtime，用于检测 web-admin 的外部写入
_watched: dict[str, float] = {}


def _init_mtimes() -> None:
    """启动时记录初始 mtime，避免首次轮询误判为变化。"""
    for path in (
        RULE_SWITCH_PATH,
        CONFIG_AWAKENING_TOML,
        daily_enabled_groups.path,
        daily_briefing_enabled_groups.path,
        weekly_enabled_groups.path,
        monthly_enabled_groups.path,
        boredom_enabled_groups.path,
    ):
        try:
            _watched[str(path)] = os.stat(path).st_mtime
        except OSError:
            _watched[str(path)] = 0.0


def _reload_if_changed() -> None:
    """H1: 检测状态文件是否被 web-admin 进程修改，有变化则 reload。"""
    checks = [
        (RULE_SWITCH_PATH, lambda: rule_switch.load(RULE_SWITCH_PATH)),
        (CONFIG_AWAKENING_TOML, reload_awakening_and_reschedule),
        (daily_enabled_groups.path, daily_enabled_groups.load),
        (daily_briefing_enabled_groups.path, daily_briefing_enabled_groups.load),
        (weekly_enabled_groups.path, weekly_enabled_groups.load),
        (monthly_enabled_groups.path, monthly_enabled_groups.load),
        (boredom_enabled_groups.path, reload_boredom_groups),
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
        svc = get_llm_service()
        await svc.startup(background=True)
        await tieba_service.startup()
        _init_mtimes()

    @driver.on_shutdown
    async def _save_on_shutdown():
        svc = get_llm_service()
        try:
            await tieba_service.shutdown()
            await svc.shutdown()
            save_all()
        finally:
            await close_persistent_stores()

    try:
        from nonebot_plugin_apscheduler import scheduler

        # 维护任务接入执行记录（#199）：与 daily_summary_plugin 的 best-effort
        # 范式一致——成功/失败两路记录，record 调用自身吞异常，任务异常原样 re-raise。
        # 懒 import scheduler_plugin：lifecycle 被 tz_tracker 插件链在模块级引入，
        # 顶层 import 会把 scheduler_plugin 的模块级副作用提前到该链上。
        def _auto_save_with_result() -> None:
            from quickquip.adapters.nonebot.scheduler_plugin import record_job_result

            try:
                save_all()
                try:
                    record_job_result("persistence_auto_save", True)
                except Exception:
                    pass
            except Exception as exc:
                try:
                    record_job_result("persistence_auto_save", False, str(exc)[:500])
                except Exception:
                    pass
                raise

        def _state_sync_with_result() -> None:
            from quickquip.adapters.nonebot.scheduler_plugin import record_job_result

            try:
                _reload_if_changed()
                try:
                    record_job_result("web_admin_state_sync", True)
                except Exception:
                    pass
            except Exception as exc:
                try:
                    record_job_result("web_admin_state_sync", False, str(exc)[:500])
                except Exception:
                    pass
                raise

        async def _action_queue_with_result() -> None:
            from quickquip.adapters.nonebot.scheduler_plugin import record_job_result

            try:
                await process_web_admin_actions()
                try:
                    record_job_result("web_admin_action_queue", True)
                except Exception:
                    pass
            except Exception as exc:
                try:
                    record_job_result("web_admin_action_queue", False, str(exc)[:500])
                except Exception:
                    pass
                raise

        scheduler.add_job(
            _auto_save_with_result,
            "interval",
            minutes=5,
            id="persistence_auto_save",
            replace_existing=True,
        )
        scheduler.add_job(
            _state_sync_with_result,
            "interval",
            seconds=30,
            id="web_admin_state_sync",
            replace_existing=True,
        )
        scheduler.add_job(
            _action_queue_with_result,
            "interval",
            seconds=5,
            id="web_admin_action_queue",
            replace_existing=True,
        )
    except ModuleNotFoundError:
        pass
