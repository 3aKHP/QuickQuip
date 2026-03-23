from __future__ import annotations

from quickquip.app.message_pipeline import llm_service, save_all
from quickquip.tieba.service import tieba_service


def register_lifecycle(driver) -> None:
    @driver.on_startup
    async def _startup_llm_runtime():
        await llm_service.startup(background=True)
        await tieba_service.startup()

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
    except ModuleNotFoundError:
        pass
