from __future__ import annotations

from quickquip.adapters.nonebot.command_parts.common import _allow_scope_management, _is_private_chat
from quickquip.app.message_pipeline import RULE_SWITCH_PATH, llm_service, reload_chat_rules_pipeline, rule_switch
from quickquip.app.message_pipeline import is_admin as _is_admin


def register_rules_commands(on_command, Message, MessageSegment) -> None:
    disable_cmd = on_command("disable", priority=10, block=True)

    @disable_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await disable_cmd.finish("私聊不支持 /disable")
        if not _is_admin(event):
            await disable_cmd.finish("仅管理员可执行此操作")
        rule_name = str(event.get_message()).strip().replace("/disable", "").strip()
        if not rule_name:
            await disable_cmd.finish("用法：/disable <rule_name>")
        if rule_switch.disable(event.group_id, rule_name):
            rule_switch.save(RULE_SWITCH_PATH)
            await disable_cmd.finish(f"已禁用规则：{rule_name}")
        await disable_cmd.finish(f"未知规则：{rule_name}")

    enable_cmd = on_command("enable", priority=10, block=True)

    @enable_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await enable_cmd.finish("私聊不支持 /enable")
        if not _is_admin(event):
            await enable_cmd.finish("仅管理员可执行此操作")
        rule_name = str(event.get_message()).strip().replace("/enable", "").strip()
        if not rule_name:
            await enable_cmd.finish("用法：/enable <rule_name>")
        if rule_switch.enable(event.group_id, rule_name):
            rule_switch.save(RULE_SWITCH_PATH)
            await enable_cmd.finish(f"已启用规则：{rule_name}")
        await enable_cmd.finish(f"未知规则：{rule_name}")

    rules_cmd = on_command("rules", priority=10, block=True)

    @rules_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await rules_cmd.finish("私聊不支持 /rules")
        await rules_cmd.finish(rule_switch.format_rules(event.group_id))

    reload_rules_cmd = on_command("reload_rules", priority=10, block=True)

    @reload_rules_cmd.handle()
    async def _(event):
        if not _allow_scope_management(event):
            await reload_rules_cmd.finish("仅管理员可执行此操作")
        try:
            summary = reload_chat_rules_pipeline()
        except Exception as exc:
            await reload_rules_cmd.finish(f"chat_rules 重载失败：{exc}")
        await reload_rules_cmd.finish(
            "chat_rules 已重载（"
            f"text {summary['text_rules']} / "
            f"context {summary['context_rules']} / "
            f"chain {summary['chain_games']} / "
            f"rate_limit {summary['rate_limit_rules']}）"
        )

    reload_personas_cmd = on_command("reload_personas", priority=10, block=True)

    @reload_personas_cmd.handle()
    async def _(event):
        if not _allow_scope_management(event):
            await reload_personas_cmd.finish("仅管理员可执行此操作")
        count, error = llm_service.reload_personas()
        if error:
            await reload_personas_cmd.finish(f"人格重载失败：{error}")
        default_persona = llm_service.config.runtime.default_persona or "(未配置)"
        await reload_personas_cmd.finish(
            f"人格已重载（{count} 个，默认：{default_persona}）"
        )
