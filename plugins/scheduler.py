try:
    import nonebot
    from nonebot_plugin_apscheduler import scheduler
except ModuleNotFoundError:
    nonebot = None
    scheduler = None

from plugins.tz_config import SCHEDULED_MESSAGES


def _register_jobs():
    if not scheduler or not SCHEDULED_MESSAGES:
        return

    bot_getter = nonebot.get_bot

    for index, entry in enumerate(SCHEDULED_MESSAGES):
        cron_expr = entry["cron"]
        group_ids = entry["group_ids"]
        message = entry["message"]

        parts = cron_expr.split()
        cron_kwargs = {
            "minute": parts[0],
            "hour": parts[1],
            "day": parts[2],
            "month": parts[3],
            "day_of_week": parts[4],
        }

        async def _send(gids=group_ids, msg=message):
            try:
                bot = bot_getter()
            except Exception:
                return
            for gid in gids:
                try:
                    await bot.send_group_msg(group_id=gid, message=msg)
                except Exception:
                    pass

        scheduler.add_job(
            _send,
            "cron",
            id=f"scheduled_msg_{index}",
            replace_existing=True,
            **cron_kwargs,
        )


_register_jobs()
