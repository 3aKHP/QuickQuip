from __future__ import annotations

from quickquip.app.message_pipeline import RULE_SWITCH_PATH, STATS_PATH, llm_service, rate_limiter, rule_switch, stats_tracker
from quickquip.app.message_pipeline import is_admin as _is_admin
from quickquip.app.message_pipeline import strip_command_name as _strip_command_name
from quickquip.search.web_search import WebSearchError, build_search_client, format_search_response
from quickquip.tieba.config import TIEBA_RULE_NAME
from quickquip.tieba.errors import TiebaLoginRequiredError, TiebaServiceError
from quickquip.tieba.service import tieba_service


def register_commands(on_command, Message, MessageSegment) -> None:
    stats_cmd = on_command("stats", priority=10, block=True)

    @stats_cmd.handle()
    async def _(event):
        await stats_cmd.finish(stats_tracker.format_stats(event.group_id))

    llm_cmd = on_command("llm", priority=10, block=True)

    @llm_cmd.handle()
    async def _(event):
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "llm")
        group_id = event.group_id
        tokens = args.split()

        if not args or args == "status":
            await llm_cmd.finish(llm_service.format_status(group_id))

        if args == "current":
            await llm_cmd.finish(llm_service.format_current(group_id))

        if args in {"mcp", "mcp status"}:
            await llm_cmd.finish(llm_service.format_mcp_status())

        if args == "providers":
            await llm_cmd.finish(llm_service.format_providers())

        if args == "personas":
            await llm_cmd.finish(llm_service.format_personas())

        if tokens[:1] == ["models"]:
            provider_id = tokens[1] if len(tokens) > 1 else None
            await llm_cmd.finish(llm_service.format_models(provider_id))

        if tokens[:2] == ["memory", "status"]:
            await llm_cmd.finish(llm_service.format_memory_status(group_id))

        if not _is_admin(event):
            await llm_cmd.finish("仅管理员可执行此操作")

        if args == "on":
            llm_service.set_group_enabled(group_id, True)
            await llm_cmd.finish("本群 LLM 已开启")

        if args == "off":
            llm_service.set_group_enabled(group_id, False)
            await llm_cmd.finish("本群 LLM 已关闭")

        if args == "reload":
            config = await llm_service.reload_runtime(background=True)
            if config.load_error:
                await llm_cmd.finish(f"LLM 配置重载失败：{config.load_error}")
            await llm_cmd.finish("LLM 配置已重载")

        if args == "clear_context":
            deleted = llm_service.clear_group_context(group_id)
            await llm_cmd.finish(f"已清空当前群的短期上下文，共删除 {deleted} 条记录")

        if tokens[:1] == ["use"] and len(tokens) >= 3:
            provider_id = tokens[1]
            model = tokens[2]
            try:
                llm_service.set_group_model(group_id, provider_id, model)
            except ValueError as exc:
                await llm_cmd.finish(str(exc))
            await llm_cmd.finish(f"本群 LLM 已切换到 {provider_id} / {model}")

        if tokens[:2] == ["persona", "use"] and len(tokens) >= 3:
            persona_id = tokens[2]
            try:
                llm_service.set_group_persona(group_id, persona_id)
            except ValueError as exc:
                await llm_cmd.finish(str(exc))
            await llm_cmd.finish(f"本群人格已切换到 {persona_id}")

        if tokens[:2] == ["trigger", "prefix"] and len(tokens) >= 3:
            try:
                llm_service.set_group_trigger_prefix(group_id, tokens[2])
            except ValueError as exc:
                await llm_cmd.finish(str(exc))
            await llm_cmd.finish(f"本群触发前缀已改为 {tokens[2]}")

        if tokens[:2] == ["trigger", "prefix_mode"] and len(tokens) >= 3:
            value = tokens[2].lower()
            if value not in {"on", "off"}:
                await llm_cmd.finish("用法：/llm trigger prefix_mode on|off")
            llm_service.set_group_allow_prefix(group_id, value == "on")
            await llm_cmd.finish(f"本群前缀触发已设为 {value}")

        if tokens[:2] == ["trigger", "at"] and len(tokens) >= 3:
            value = tokens[2].lower()
            if value not in {"on", "off"}:
                await llm_cmd.finish("用法：/llm trigger at on|off")
            llm_service.set_group_allow_at(group_id, value == "on")
            await llm_cmd.finish(f"本群艾特触发已设为 {value}")

        if tokens[:2] == ["memory", "on"]:
            llm_service.set_group_memory_enabled(group_id, True)
            await llm_cmd.finish("本群记忆注入已开启")

        if tokens[:2] == ["memory", "off"]:
            llm_service.set_group_memory_enabled(group_id, False)
            await llm_cmd.finish("本群记忆注入已关闭")

        await llm_cmd.finish(
            "LLM 命令用法：/llm status|current|on|off|providers|models [provider]|use <provider> <model>|"
            "personas|persona use <id>|trigger prefix <value>|trigger prefix_mode on|off|trigger at on|off|"
            "memory status|memory on|memory off|clear_context|reload|mcp status"
        )

    search_cmd = on_command("search", priority=10, block=True)

    @search_cmd.handle()
    async def _(event):
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "search")
        if not args:
            await search_cmd.finish("用法：/search <query> 或 /search news <query>")
        if not rate_limiter.allow("web_search", event.user_id):
            await search_cmd.finish("搜索过于频繁，请稍后再试")

        tokens = args.split()
        topic = "general"
        query = args
        if tokens and tokens[0].lower() in {"general", "news", "finance"}:
            topic = tokens[0].lower()
            query = args[len(tokens[0]):].strip()
        if not query:
            await search_cmd.finish("搜索词不能为空")

        try:
            response = await build_search_client().search(query, topic=topic, max_results=5)
        except WebSearchError as exc:
            await search_cmd.finish(f"联网搜索失败：{exc}")
        await search_cmd.finish(format_search_response(response))

    tieba_cmd = on_command("tieba", priority=10, block=True)

    @tieba_cmd.handle()
    async def _(event):
        if not rule_switch.is_enabled(event.group_id, TIEBA_RULE_NAME):
            await tieba_cmd.finish("本群已关闭贴吧随机搬运功能")

        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "tieba")
        normalized_args = args.lower()

        if not args or normalized_args == "random":
            if not rate_limiter.allow(TIEBA_RULE_NAME, event.user_id):
                await tieba_cmd.finish("贴吧搬运过于频繁，请稍后再试")
            thread = await tieba_service.get_random_thread()
            if thread is None:
                if tieba_service.store.login_required:
                    await tieba_cmd.finish("贴吧登录态需要人工续签，请让管理员先运行 python dev/tools/tieba_login.py")
                await tieba_cmd.finish("当前贴吧池为空，请稍后再试或让管理员执行 /tieba refresh")
            tieba_service.mark_sent(thread.tid)
            stats_tracker.record_trigger(event.group_id, TIEBA_RULE_NAME)
            message = Message([MessageSegment.text(tieba_service.build_thread_preview(thread))])
            image_url = thread.cover_image_url or (thread.image_urls[0] if thread.image_urls else "")
            if image_url:
                message.append(MessageSegment.image(image_url))
            await tieba_cmd.finish(message)

        if normalized_args == "text":
            if not rate_limiter.allow(TIEBA_RULE_NAME, event.user_id):
                await tieba_cmd.finish("贴吧搬运过于频繁，请稍后再试")
            thread = await tieba_service.get_random_thread()
            if thread is None:
                if tieba_service.store.login_required:
                    await tieba_cmd.finish("贴吧登录态需要人工续签，请让管理员先运行 python dev/tools/tieba_login.py")
                await tieba_cmd.finish("当前贴吧池为空，请稍后再试或让管理员执行 /tieba refresh")
            tieba_service.mark_sent(thread.tid)
            stats_tracker.record_trigger(event.group_id, TIEBA_RULE_NAME)
            await tieba_cmd.finish(tieba_service.build_thread_preview(thread))

        if normalized_args == "status":
            await tieba_cmd.finish(tieba_service.format_status())

        if normalized_args == "refresh":
            if not _is_admin(event):
                await tieba_cmd.finish("仅管理员可执行此操作")
            try:
                result = await tieba_service.sync_now(force=True)
            except TiebaLoginRequiredError as exc:
                await tieba_cmd.finish(f"{exc}\n请运行 python dev/tools/tieba_login.py 续签登录态")
            except TiebaServiceError as exc:
                await tieba_cmd.finish(f"贴吧同步失败：{exc}")
            await tieba_cmd.finish(str(result["message"]))

        await tieba_cmd.finish("贴吧命令用法：/tieba | /tieba text | /tieba status | /tieba refresh")

    reset_stats_cmd = on_command("reset_stats", priority=10, block=True)

    @reset_stats_cmd.handle()
    async def _(event):
        if not _is_admin(event):
            await reset_stats_cmd.finish("仅管理员可执行此操作")
        stats_tracker.reset(event.group_id)
        stats_tracker.save(STATS_PATH)
        await reset_stats_cmd.finish("统计数据已重置")

    disable_cmd = on_command("disable", priority=10, block=True)

    @disable_cmd.handle()
    async def _(event):
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
        await rules_cmd.finish(rule_switch.format_rules(event.group_id))

    remember_cmd = on_command("remember", priority=10, block=True)

    @remember_cmd.handle()
    async def _(event):
        if not _is_admin(event):
            await remember_cmd.finish("仅管理员可执行此操作")
        content = _strip_command_name(str(event.get_message()).strip(), "remember")
        if not content:
            await remember_cmd.finish("用法：/remember <要保存的群记忆>")
        memory_id = llm_service.remember_group_memory(event.group_id, content)
        await remember_cmd.finish(f"已写入群记忆 #{memory_id}")

    memories_cmd = on_command("memories", priority=10, block=True)

    @memories_cmd.handle()
    async def _(event):
        keyword = _strip_command_name(str(event.get_message()).strip(), "memories")
        reply = llm_service.format_memories(event.group_id, keyword=keyword or None)
        await memories_cmd.finish(reply)

    forget_cmd = on_command("forget", priority=10, block=True)

    @forget_cmd.handle()
    async def _(event):
        if not _is_admin(event):
            await forget_cmd.finish("仅管理员可执行此操作")
        keyword = _strip_command_name(str(event.get_message()).strip(), "forget")
        if not keyword:
            await forget_cmd.finish("用法：/forget <关键词>")
        deleted = llm_service.forget_group_memories(event.group_id, keyword)
        await forget_cmd.finish(f"已删除 {deleted} 条群记忆")
