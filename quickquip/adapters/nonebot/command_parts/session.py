from __future__ import annotations

from quickquip.adapters.nonebot.command_parts.common import _is_private_chat, _parse_preset, _parse_resume, _strip_command_name
from quickquip.app.message_pipeline import llm_service, stats_tracker


def register_session_commands(on_command, Message, MessageSegment) -> None:
    start_session_cmd = on_command("start_sesssion", priority=10, block=True)
    start_session_alias_cmd = on_command("start_session", priority=10, block=True)
    end_session_cmd = on_command("end_session", priority=10, block=True)

    async def _start_private_session(event, matcher, cmd_name: str) -> None:
        if not _is_private_chat(event):
            await matcher.finish("该命令仅支持私聊")
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, cmd_name)
        has_resume, resume_num = _parse_resume(args)
        if has_resume:
            result = llm_service.resume_private_session(event.user_id, resume_num)
            if "error" in result:
                await matcher.finish(result["error"])
            preset_override = _parse_preset(args)
            if preset_override:
                scope_key = llm_service.build_chat_scope_key(event.user_id, "private")
                llm_service._session_presets[scope_key] = preset_override
            preset = preset_override or result.get("preset", "")
            msg = f"已恢复存档 #{result['archive_number']}（{result['message_count']} 条消息）"
            if preset:
                preview = preset[:80] + ("..." if len(preset) > 80 else "")
                msg += f"\n附加设定：{preview}"
            await matcher.finish(msg)
        preset = _parse_preset(args)
        llm_service.start_private_session(event.user_id, preset=preset)
        msg = (
            f"当前私聊会话已开启，之后的普通消息、图片和引用回复都会进入 LLM。"
            f" 当前上下文上限为 {llm_service.get_default_history_limit('private')} 条。"
        )
        if preset:
            preview = preset[:80] + ("..." if len(preset) > 80 else "")
            msg += f"\n附加设定：{preview}"
        await matcher.finish(msg)

    async def _end_private_session(event, matcher, cmd_name: str) -> None:
        if not _is_private_chat(event):
            await matcher.finish("该命令仅支持私聊")
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, cmd_name)
        no_save = "--no-save" in args
        result = llm_service.end_private_session(event.user_id, save=not no_save)
        deleted = result["deleted"]
        archive_number = result.get("archive_number")
        if archive_number is not None:
            await matcher.finish(f"当前私聊会话已结束，已存档为 #{archive_number}（{deleted} 条消息）。")
        else:
            suffix = "（未存档）" if no_save else ""
            await matcher.finish(f"当前私聊会话已结束，并清空了 {deleted} 条短期上下文。{suffix}")

    @start_session_cmd.handle()
    async def _(event):
        await _start_private_session(event, start_session_cmd, "start_sesssion")

    @start_session_alias_cmd.handle()
    async def _(event):
        await _start_private_session(event, start_session_alias_cmd, "start_session")

    @end_session_cmd.handle()
    async def _(event):
        await _end_private_session(event, end_session_cmd, "end_session")

    resume_session_cmd = on_command("resume_session", priority=10, block=True)

    @resume_session_cmd.handle()
    async def _(event):
        if not _is_private_chat(event):
            await resume_session_cmd.finish("该命令仅支持私聊")
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "resume_session").strip()
        archive_number = int(args) if args.isdigit() else None
        result = llm_service.resume_private_session(event.user_id, archive_number)
        if "error" in result:
            await resume_session_cmd.finish(result["error"])
        preset = result.get("preset", "")
        msg = f"已恢复存档 #{result['archive_number']}（{result['message_count']} 条消息）"
        if preset:
            preview = preset[:80] + ("..." if len(preset) > 80 else "")
            msg += f"\n附加设定：{preview}"
        await resume_session_cmd.finish(msg)

    sessions_cmd = on_command("sessions", priority=10, block=True)

    @sessions_cmd.handle()
    async def _(event):
        if not _is_private_chat(event):
            await sessions_cmd.finish("该命令仅支持私聊")
        await sessions_cmd.finish(llm_service.format_session_archives(event.user_id))

    delete_session_cmd = on_command("delete_session", priority=10, block=True)

    @delete_session_cmd.handle()
    async def _(event):
        if not _is_private_chat(event):
            await delete_session_cmd.finish("该命令仅支持私聊")
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "delete_session").strip()
        if not args.isdigit():
            await delete_session_cmd.finish("用法：/delete_session <存档编号>")
        archive_number = int(args)
        deleted = llm_service.delete_session_archive_for_user(event.user_id, archive_number)
        if deleted:
            await delete_session_cmd.finish(f"已删除存档 #{archive_number}。")
        else:
            await delete_session_cmd.finish(f"存档 #{archive_number} 不存在。")

    stats_cmd = on_command("stats", priority=10, block=True)

    @stats_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await stats_cmd.finish("私聊不支持 /stats")
        await stats_cmd.finish(stats_tracker.format_stats(event.group_id))
