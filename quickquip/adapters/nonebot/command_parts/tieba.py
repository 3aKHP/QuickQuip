from __future__ import annotations

from quickquip.adapters.nonebot.command_parts.common import _is_admin, _is_private_chat, _parse_tieba_command_args, _strip_command_name
from quickquip.app.message_pipeline import STATS_PATH, rate_limiter, rule_switch, stats_tracker
from quickquip.tieba.config import TIEBA_RULE_NAME
from quickquip.tieba.errors import TiebaLoginRequiredError, TiebaServiceError
from quickquip.tieba.service import tieba_service


def register_tieba_commands(on_command, Message, MessageSegment) -> None:
    tieba_cmd = on_command("tieba", priority=10, block=True)

    @tieba_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await tieba_cmd.finish("私聊不支持 /tieba")
        if not rule_switch.is_enabled(event.group_id, TIEBA_RULE_NAME):
            await tieba_cmd.finish("本群已关闭贴吧随机搬运功能")

        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "tieba")
        action, forum_keyword, text_only = _parse_tieba_command_args(args)

        if action == "random":
            if not rate_limiter.allow(TIEBA_RULE_NAME, event.user_id):
                await tieba_cmd.finish("贴吧搬运过于频繁，请稍后再试")
            try:
                thread = await tieba_service.get_random_thread(forum_keyword=forum_keyword)
            except TiebaServiceError as exc:
                await tieba_cmd.finish(f"贴吧搬运失败：{exc}")
            if thread is None:
                if tieba_service.is_login_required(forum_keyword):
                    await tieba_cmd.finish("贴吧登录态需要人工续签，请让管理员先运行 python dev/tools/tieba_login.py")
                if forum_keyword:
                    await tieba_cmd.finish(f"{forum_keyword}吧消息池为空，请稍后再试或让管理员执行 /tieba refresh {forum_keyword}")
                await tieba_cmd.finish("当前贴吧池为空，请稍后再试或让管理员执行 /tieba refresh")
            tieba_service.mark_sent(thread)
            stats_tracker.record_trigger(event.group_id, TIEBA_RULE_NAME)
            if text_only:
                await tieba_cmd.finish(tieba_service.build_thread_preview(thread))
            message = Message([MessageSegment.text(tieba_service.build_thread_preview(thread))])
            image_url = thread.cover_image_url or (thread.image_urls[0] if thread.image_urls else "")
            if image_url:
                message.append(MessageSegment.image(image_url))
            await tieba_cmd.finish(message)

        if action == "status":
            try:
                await tieba_cmd.finish(tieba_service.format_status(forum_keyword=forum_keyword))
            except TiebaServiceError as exc:
                await tieba_cmd.finish(f"贴吧状态读取失败：{exc}")

        if action == "source":
            try:
                await tieba_cmd.finish(tieba_service.format_sources(forum_keyword=forum_keyword))
            except TiebaServiceError as exc:
                await tieba_cmd.finish(f"贴吧来源读取失败：{exc}")

        if action == "refresh":
            if not _is_admin(event):
                await tieba_cmd.finish("仅管理员可执行此操作")
            try:
                target_forum = None if forum_keyword in {None, "", "all"} else forum_keyword
                result = await tieba_service.sync_now(force=True, forum_keyword=target_forum)
            except TiebaLoginRequiredError as exc:
                await tieba_cmd.finish(f"{exc}\n请运行 python dev/tools/tieba_login.py 续签登录态")
            except TiebaServiceError as exc:
                await tieba_cmd.finish(f"贴吧同步失败：{exc}")
            await tieba_cmd.finish(str(result["message"]))

        await tieba_cmd.finish(
            "贴吧命令用法：/tieba [贴吧名] | /tieba text [贴吧名] | "
            "/tieba status [贴吧名] | /tieba source [贴吧名] | /tieba refresh [贴吧名|all]"
        )

    reset_stats_cmd = on_command("reset_stats", priority=10, block=True)

    @reset_stats_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await reset_stats_cmd.finish("私聊不支持 /reset_stats")
        if not _is_admin(event):
            await reset_stats_cmd.finish("仅管理员可执行此操作")
        stats_tracker.reset(event.group_id)
        stats_tracker.save(STATS_PATH)
        await reset_stats_cmd.finish("统计数据已重置")

    tieba_peek_cmd = on_command("tieba_peek", priority=10, block=True)

    @tieba_peek_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await tieba_peek_cmd.finish("私聊不支持 /tieba_peek")
        if not _is_admin(event):
            await tieba_peek_cmd.finish("仅管理员可执行此操作")
        text = str(event.get_message()).strip()
        forum_keyword = _strip_command_name(text, "tieba_peek").strip()
        if not forum_keyword:
            await tieba_peek_cmd.finish("用法：/tieba_peek <贴吧名>")
        await tieba_peek_cmd.send(f"正在从 {forum_keyword}吧 现爬，请稍候…")
        try:
            thread = await tieba_service.peek_random_thread(forum_keyword)
        except TiebaLoginRequiredError:
            await tieba_peek_cmd.finish("贴吧登录态需要人工续签，请运行 python dev/tools/tieba_login.py")
        except TiebaServiceError as exc:
            await tieba_peek_cmd.finish(f"现爬失败：{exc}")
        if thread is None:
            await tieba_peek_cmd.finish(f"{forum_keyword}吧未找到有效帖子")
        message = Message([MessageSegment.text(tieba_service.build_thread_preview(thread))])
        image_url = thread.cover_image_url or (thread.image_urls[0] if thread.image_urls else "")
        if image_url:
            message.append(MessageSegment.image(image_url))
        await tieba_peek_cmd.finish(message)
