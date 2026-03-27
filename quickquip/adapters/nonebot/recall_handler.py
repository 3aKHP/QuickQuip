from __future__ import annotations

from quickquip.app.message_pipeline import llm_service


def register_recall_handlers(on_notice):
    recall_matcher = on_notice(priority=10, block=False)

    @recall_matcher.handle()
    async def _(event):
        notice_type = getattr(event, "notice_type", "")
        if notice_type not in ("group_recall", "friend_recall"):
            return

        message_id = str(getattr(event, "message_id", ""))
        if not message_id:
            return

        if notice_type == "group_recall":
            scope_key = str(event.group_id)
        else:
            user_id = str(event.user_id)
            scope_key = llm_service.build_chat_scope_key(user_id, chat_type="private")

        llm_service.delete_message_from_context(scope_key, message_id)

    return recall_matcher
