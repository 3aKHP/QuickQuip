from __future__ import annotations

from quickquip.adapters.nonebot.command_parts._chat_utils import _chat_id, _chat_type
from quickquip.adapters.nonebot.command_parts.common import _strip_command_name
from quickquip.app.message_pipeline import _ensure_llm_bindings, get_llm_service


def register_skills_commands(on_command, Message, MessageSegment) -> None:
    skill_cmd = on_command("skill", priority=10, block=True)

    @skill_cmd.handle()
    async def _(event):
        args = _strip_command_name(str(event.get_message()).strip(), "skill").strip()

        if args != "list":
            await skill_cmd.finish("用法：/skill list —— 查看已安装与当前会话已激活的 Skill")

        _ensure_llm_bindings()
        svc = get_llm_service()
        await skill_cmd.finish(
            svc.format_skill_list(_chat_id(event), chat_type=_chat_type(event))
        )
