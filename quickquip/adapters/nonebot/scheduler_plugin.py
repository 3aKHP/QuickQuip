import logging

try:
    import nonebot
    from nonebot_plugin_apscheduler import scheduler
except ModuleNotFoundError:
    nonebot = None
    scheduler = None

from quickquip.chat.config import SCHEDULED_MESSAGES

logger = logging.getLogger(__name__)

# ── Job result tracking ──────────────────────────────────────────────────────

_job_run_results: dict[str, dict] = {}


def record_job_result(job_id: str, success: bool, error: str | None = None):
    """Record the last run result of a scheduled job. Best-effort only."""
    from datetime import datetime

    _job_run_results[job_id] = {
        "last_run": datetime.now().isoformat(),
        "last_status": "ok" if success else "error",
        "last_error": error[:500] if error else None,
    }


def get_job_results() -> dict:
    """Return a shallow copy of all recorded job results."""
    return dict(_job_run_results)


# ── Job registration ─────────────────────────────────────────────────────────


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

        async def _send(gids=group_ids, msg=message, _idx=index):
            job_id = f"scheduled_msg_{_idx}"
            try:
                try:
                    bot = bot_getter()
                except Exception:
                    logger.warning("scheduled_msg: bot not available, skipping")
                    try:
                        record_job_result(job_id, True)
                    except Exception:
                        pass
                    return
                for gid in gids:
                    try:
                        await bot.send_group_msg(group_id=gid, message=msg)
                    except Exception:
                        logger.warning("scheduled_msg: failed to send to group %s", gid, exc_info=True)
                try:
                    record_job_result(job_id, True)
                except Exception:
                    pass
            except Exception as exc:
                try:
                    record_job_result(job_id, False, str(exc)[:500])
                except Exception:
                    pass
                raise

        scheduler.add_job(
            _send,
            "cron",
            id=f"scheduled_msg_{index}",
            replace_existing=True,
            **cron_kwargs,
        )


_register_jobs()


# ── Festival check ────────────────────────────────────────────────────────────


def _register_festival_job() -> None:
    if not scheduler:
        return
    if nonebot is None:
        return

    from quickquip.chat.festival import check_today_festival, get_festival_greeting
    from quickquip.app.message_pipeline import daily_enabled_groups

    bot_getter = nonebot.get_bot

    async def _check_and_greet() -> None:
        festival = check_today_festival()
        if festival is None:
            return

        greeting = get_festival_greeting()
        if not greeting:
            return

        try:
            bot = bot_getter()
        except Exception:
            logger.warning("festival_check: bot not available, skipping greeting")
            return

        full_greeting = f"【{festival.name}】{greeting}"
        for gid in daily_enabled_groups.all_groups():
            try:
                await bot.send_group_msg(group_id=int(gid), message=full_greeting)
            except Exception:
                logger.warning(
                    "festival_check: failed to send greeting to group %s",
                    gid, exc_info=True,
                )

    scheduler.add_job(
        _check_and_greet,
        "cron",
        id="festival_check",
        replace_existing=True,
        hour="1",
        minute="0",
    )
    logger.info("festival_check: job registered (daily at 01:00)")


_register_festival_job()
