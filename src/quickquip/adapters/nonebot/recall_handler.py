from __future__ import annotations

from quickquip.app.message_pipeline import (
    _ensure_llm_bindings,
    get_llm_service,
    record_group_recall,
)


def register_recall_handlers(on_notice):
    recall_matcher = on_notice(priority=10, block=False)

    @recall_matcher.handle()
    async def _(event):
        _ensure_llm_bindings()
        svc = get_llm_service()

        notice_type = getattr(event, "notice_type", "")
        if notice_type not in ("group_recall", "friend_recall"):
            return

        message_id = str(getattr(event, "message_id", ""))
        if not message_id:
            return

        if notice_type == "group_recall":
            group_id = event.group_id
            scope_key = str(group_id)
            # 群撤回同时落归档旁表：历史查询据此屏蔽该消息正文（#72）。
            record_group_recall(group_id, message_id)
        else:
            user_id = str(event.user_id)
            scope_key = svc.build_chat_scope_key(user_id, chat_type="private")

        svc.delete_message_from_context(scope_key, message_id)

    return recall_matcher
