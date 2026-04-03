import logging

try:
    import nonebot
    from nonebot_plugin_apscheduler import scheduler
except ModuleNotFoundError:
    nonebot = None
    scheduler = None

from quickquip.chat.config import SCHEDULED_MESSAGES

logger = logging.getLogger(__name__)


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
                logger.warning("scheduled_msg: bot not available, skipping")
                return
            for gid in gids:
                try:
                    await bot.send_group_msg(group_id=gid, message=msg)
                except Exception:
                    logger.warning("scheduled_msg: failed to send to group %s", gid, exc_info=True)

        scheduler.add_job(
            _send,
            "cron",
            id=f"scheduled_msg_{index}",
            replace_existing=True,
            **cron_kwargs,
        )


_register_jobs()
