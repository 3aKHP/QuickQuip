from __future__ import annotations

from quickquip.adapters.nonebot.command_parts.common import _allow_scope_management, _chat_id, _chat_label, _chat_type, _is_private_chat, _strip_command_name
from quickquip.app.message_pipeline import _ensure_llm_bindings, get_llm_service, get_sender_name, offline_message_store


def register_memory_commands(on_command, Message, MessageSegment) -> None:
    remember_cmd = on_command("remember", priority=10, block=True)

    @remember_cmd.handle()
    async def _(event):
        if not _allow_scope_management(event):
            await remember_cmd.finish("仅管理员可执行此操作")
        content = _strip_command_name(str(event.get_message()).strip(), "remember")
        if not content:
            await remember_cmd.finish("用法：/remember <要保存的记忆>")
        _ensure_llm_bindings()
        svc = get_llm_service()
        chat_type = _chat_type(event)
        chat_id = _chat_id(event)
        memory_id = svc.remember_memory(chat_id, content, chat_type=chat_type)
        await remember_cmd.finish(f"已写入{_chat_label(event)}记忆 #{memory_id}")

    memories_cmd = on_command("memories", priority=10, block=True)

    @memories_cmd.handle()
    async def _(event):
        _ensure_llm_bindings()
        svc = get_llm_service()
        keyword = _strip_command_name(str(event.get_message()).strip(), "memories")
        reply = svc.format_memories(_chat_id(event), keyword=keyword or None, chat_type=_chat_type(event))
        await memories_cmd.finish(reply)

    forget_cmd = on_command("forget", priority=10, block=True)

    @forget_cmd.handle()
    async def _(event):
        if not _allow_scope_management(event):
            await forget_cmd.finish("仅管理员可执行此操作")
        keyword = _strip_command_name(str(event.get_message()).strip(), "forget")
        if not keyword:
            await forget_cmd.finish("用法：/forget <关键词>")
        _ensure_llm_bindings()
        svc = get_llm_service()
        deleted = svc.forget_memories(_chat_id(event), keyword, chat_type=_chat_type(event))
        await forget_cmd.finish(f"已删除{_chat_label(event)}中的 {deleted} 条记忆")

    forget_all_cmd = on_command("forget_all", priority=10, block=True)

    @forget_all_cmd.handle()
    async def _(event):
        if not _allow_scope_management(event):
            await forget_all_cmd.finish("仅管理员可执行此操作")
        _ensure_llm_bindings()
        svc = get_llm_service()
        deleted = svc.clear_memories(_chat_id(event), chat_type=_chat_type(event))
        await forget_all_cmd.finish(f"已清空{_chat_label(event)}全部长期记忆（共 {deleted} 条）")

    tell_cmd = on_command("tell", priority=10, block=True)

    @tell_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await tell_cmd.finish("该命令仅支持群聊")
        to_user_id = None
        content_parts = []
        at_found = False
        for seg in event.get_message():
            seg_type = getattr(seg, "type", None)
            data = getattr(seg, "data", {})
            if seg_type == "at" and not at_found:
                qq = str(data.get("qq", "") or "").strip()
                if qq and qq != "all":
                    to_user_id = qq
                    at_found = True
            elif seg_type == "text" and at_found:
                part = str(data.get("text", "") or "").strip()
                if part:
                    content_parts.append(part)
        if not to_user_id:
            await tell_cmd.finish("用法：/tell @某人 <内容>")
        if str(to_user_id) == str(event.user_id):
            await tell_cmd.finish("不能给自己留言")
        content = " ".join(content_parts).strip()
        if not content:
            await tell_cmd.finish("留言内容不能为空")
        offline_message_store.add(
            group_id=event.group_id,
            from_user_id=event.user_id,
            from_sender_name=get_sender_name(event),
            to_user_id=to_user_id,
            content=content,
        )
        await tell_cmd.finish("留言已存，TA 下次发言时会收到")

    tells_cmd = on_command("tells", priority=10, block=True)

    @tells_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await tells_cmd.finish("该命令仅支持群聊")
        pending = offline_message_store.list_pending_for(event.group_id, event.user_id)
        if not pending:
            await tells_cmd.finish("没有待接收的留言")
        lines = [f"有 {len(pending)} 条留言等着你："]
        for m in pending:
            lines.append(m.format_display())
        await tells_cmd.finish("\n".join(lines))

    untell_cmd = on_command("untell", priority=10, block=True)

    @untell_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await untell_cmd.finish("该命令仅支持群聊")
        to_user_id = offline_message_store.retract_latest(event.group_id, event.user_id)
        if to_user_id is None:
            await untell_cmd.finish("没有可撤回的留言")
        await untell_cmd.finish(f"已撤回最新留言（收件人：{to_user_id}）")
