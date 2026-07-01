from __future__ import annotations

from quickquip.adapters.nonebot.command_parts.common import _allow_scope_management, _chat_id, _chat_label, _chat_type, _parse_preset, _parse_resume, _strip_command_name, _strip_leading_command_token
from quickquip.app.message_pipeline import _ensure_llm_bindings, get_llm_service, get_sender_name, rate_limiter, stats_tracker
from quickquip.common.bot_action_trace import bot_action_trace
from quickquip.llm.rendering import render_message_for_llm, render_reply_for_llm
from quickquip.search.web_search import SearXNGSearchClient, WebSearchError, format_search_response


def register_llm_commands(on_command, Message, MessageSegment) -> None:
    llm_cmd = on_command("llm", priority=10, block=True)

    @llm_cmd.handle()
    async def _(event):
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "llm")
        chat_type = _chat_type(event)
        chat_id = _chat_id(event)
        scope_label = _chat_label(event)
        tokens = args.split()

        _ensure_llm_bindings()
        svc = get_llm_service()

        if not args or args == "status":
            await llm_cmd.finish(svc.format_status(chat_id, chat_type=chat_type))

        if args == "current":
            await llm_cmd.finish(svc.format_current(chat_id, chat_type=chat_type))

        if tokens[:1] == ["health"]:
            await llm_cmd.finish(
                await svc.format_health(
                    chat_id,
                    chat_type=chat_type,
                    verbose=len(tokens) > 1 and tokens[1] in {"verbose", "detail", "full"},
                )
            )

        if args == "probe":
            if not _allow_scope_management(event):
                await llm_cmd.finish("仅管理员可执行此操作")
            await llm_cmd.send("正在并发探活所有 provider，请稍候…")
            await llm_cmd.finish(await svc.format_provider_probe())

        if args in {"mcp", "mcp status"}:
            await llm_cmd.finish(svc.format_mcp_status())

        if args == "mcp reload":
            if not _allow_scope_management(event):
                await llm_cmd.finish("仅管理员可执行此操作")
            await llm_cmd.send("正在拉取 MCP 镜像并重连，请稍候…")
            await svc.reload_mcp(background=False)
            await llm_cmd.finish(svc.format_mcp_status())

        if args == "providers":
            await llm_cmd.finish(svc.format_providers())

        if args == "personas":
            await llm_cmd.finish(svc.format_personas(chat_type=chat_type))

        if tokens[:1] == ["models"]:
            provider_id = tokens[1] if len(tokens) > 1 else None
            await llm_cmd.finish(svc.format_models(provider_id))

        if tokens[:2] == ["memory", "status"]:
            await llm_cmd.finish(svc.format_memory_status(chat_id, chat_type=chat_type))

        if not _allow_scope_management(event):
            await llm_cmd.finish("仅管理员可执行此操作")

        if tokens[:1] == ["on"]:
            if chat_type == "private":
                has_resume, resume_num = _parse_resume(args)
                if has_resume:
                    result = svc.resume_private_session(chat_id, resume_num)
                    if "error" in result:
                        await llm_cmd.finish(result["error"])
                    preset_override = _parse_preset(args)
                    if preset_override:
                        scope_key = svc.build_chat_scope_key(chat_id, "private")
                        svc._session_presets[scope_key] = preset_override
                    preset = preset_override or result.get("preset", "")
                    msg = f"已恢复存档 #{result['archive_number']}（{result['message_count']} 条消息）"
                    if preset:
                        preview = preset[:80] + ("..." if len(preset) > 80 else "")
                        msg += f"\n附加设定：{preview}"
                    await llm_cmd.finish(msg)
                preset = _parse_preset(args)
                svc.start_private_session(chat_id, preset=preset)
                msg = f"{scope_label}会话已开启。也可以直接使用 /start_sesssion，当前上下文上限为 {svc.get_default_history_limit('private')} 条。"
                if preset:
                    preview = preset[:80] + ("..." if len(preset) > 80 else "")
                    msg += f"\n附加设定：{preview}"
                await llm_cmd.finish(msg)
            else:
                svc.set_chat_enabled(chat_id, True, chat_type=chat_type)
                await llm_cmd.finish(f"{scope_label} LLM 已开启")

        if tokens[:1] == ["off"]:
            if chat_type == "private":
                no_save = "--no-save" in args
                result = svc.end_private_session(chat_id, save=not no_save)
                deleted = result["deleted"]
                archive_number = result.get("archive_number")
                if archive_number is not None:
                    await llm_cmd.finish(f"{scope_label}会话已结束，已存档为 #{archive_number}（{deleted} 条消息）。")
                else:
                    suffix = "（未存档）" if no_save else ""
                    await llm_cmd.finish(f"{scope_label}会话已结束，并清空了 {deleted} 条短期上下文。{suffix}")
            else:
                svc.set_chat_enabled(chat_id, False, chat_type=chat_type)
                await llm_cmd.finish(f"{scope_label} LLM 已关闭")

        if args == "reload":
            if not _allow_scope_management(event):
                await llm_cmd.finish("仅管理员可执行此操作")
            svc.reset_chat_history_limit(chat_id, chat_type=chat_type)
            config = await svc.reload_runtime(background=True)
            if config.load_error:
                await llm_cmd.finish(f"LLM 配置重载失败：{config.load_error}")
            await llm_cmd.send("LLM 配置已重载，正在探活当前 provider/model…")
            await llm_cmd.finish(await svc.format_current_provider_probe(chat_id, chat_type=chat_type))

        if args == "clear_context":
            deleted = svc.clear_context(chat_id, chat_type=chat_type)
            await llm_cmd.finish(f"已清空{scope_label}的短期上下文，共删除 {deleted} 条记录")

        if tokens[:1] == ["delete_msg"]:
            reply = getattr(event, "reply", None)
            target_msg_id = ""
            if reply:
                target_msg_id = str(getattr(reply, "message_id", "") or "").strip()
            if not target_msg_id and len(tokens) >= 2:
                target_msg_id = tokens[1].strip()
            if not target_msg_id:
                await llm_cmd.finish("用法：引用一条消息并发送 /llm delete_msg，或 /llm delete_msg <消息ID>")
            scope_key = svc.build_chat_scope_key(chat_id, chat_type)
            deleted = svc.delete_message_from_context(scope_key, target_msg_id)
            if deleted:
                await llm_cmd.finish(f"已从上下文中删除消息 {target_msg_id}")
            else:
                await llm_cmd.finish(f"未找到消息 {target_msg_id}，可能已过期或未被记录")

        if tokens[:1] == ["use"] and len(tokens) >= 2:
            provider_id = tokens[1]
            model = tokens[2] if len(tokens) >= 3 else ""
            try:
                resolved = svc.set_chat_model(chat_id, provider_id, model, chat_type=chat_type)
            except ValueError as exc:
                await llm_cmd.finish(str(exc))
            if model and model != resolved:
                msg = f"{scope_label} LLM 已切换到 {provider_id} / {resolved}（← {model}）"
            else:
                msg = f"{scope_label} LLM 已切换到 {provider_id} / {resolved}"
            await llm_cmd.finish(msg)

        if tokens[:2] == ["persona", "use"] and len(tokens) >= 3:
            persona_id = tokens[2]
            try:
                svc.set_chat_persona(chat_id, persona_id, chat_type=chat_type)
            except ValueError as exc:
                await llm_cmd.finish(str(exc))
            await llm_cmd.finish(f"{scope_label}人格已切换到 {persona_id}")

        if tokens[:2] == ["trigger", "prefix"] and len(tokens) >= 3:
            try:
                svc.set_chat_trigger_prefix(chat_id, tokens[2], chat_type=chat_type)
            except ValueError as exc:
                await llm_cmd.finish(str(exc))
            await llm_cmd.finish(f"{scope_label}触发前缀已改为 {tokens[2]}")

        if tokens[:2] == ["trigger", "prefix_mode"] and len(tokens) >= 3:
            value = tokens[2].lower()
            if value not in {"on", "off"}:
                await llm_cmd.finish("用法：/llm trigger prefix_mode on|off")
            svc.set_chat_allow_prefix(chat_id, value == "on", chat_type=chat_type)
            await llm_cmd.finish(f"{scope_label}前缀触发已设为 {value}")

        if tokens[:2] == ["trigger", "at"] and len(tokens) >= 3:
            if chat_type == "private":
                await llm_cmd.finish("私聊仅支持前缀触发，不支持艾特触发")
            value = tokens[2].lower()
            if value not in {"on", "off"}:
                await llm_cmd.finish("用法：/llm trigger at on|off")
            svc.set_group_allow_at(chat_id, value == "on")
            await llm_cmd.finish(f"{scope_label}艾特触发已设为 {value}")

        if tokens[:2] == ["memory", "on"]:
            svc.set_chat_memory_enabled(chat_id, True, chat_type=chat_type)
            await llm_cmd.finish(f"{scope_label}记忆注入已开启")

        if tokens[:2] == ["memory", "off"]:
            svc.set_chat_memory_enabled(chat_id, False, chat_type=chat_type)
            await llm_cmd.finish(f"{scope_label}记忆注入已关闭")

        if tokens[:1] == ["auto_memory"] and len(tokens) >= 2:
            sub = tokens[1].lower()
            if sub == "on":
                svc.set_chat_auto_memory_enabled(chat_id, True, chat_type=chat_type)
                await llm_cmd.finish(f"{scope_label}自动记忆抽取已开启")
            if sub == "off":
                svc.set_chat_auto_memory_enabled(chat_id, False, chat_type=chat_type)
                await llm_cmd.finish(f"{scope_label}自动记忆抽取已关闭")
            if sub == "reset":
                svc.set_chat_auto_memory_enabled(chat_id, None, chat_type=chat_type)
                default = "开" if svc.config.runtime.auto_memory_enabled else "关"
                await llm_cmd.finish(f"{scope_label}自动记忆抽取已跟随全局默认（当前：{default}）")
            if sub == "status":
                settings = svc.get_chat_settings(chat_id, chat_type=chat_type)
                default = "开" if svc.config.runtime.auto_memory_enabled else "关"
                current = "开" if settings.auto_memory_enabled else "关"
                await llm_cmd.finish(
                    f"{scope_label}自动记忆抽取：{current}（全局默认 {default}）"
                )

        if tokens[:1] == ["context_limit"] and len(tokens) >= 2:
            value = tokens[1].lower()
            if value in {"reset", "off"}:
                svc.reset_chat_history_limit(chat_id, chat_type=chat_type)
                await llm_cmd.finish(
                    f"{scope_label}上下文上限已重置为默认（{svc.get_default_history_limit(chat_type)} 条）"
                )
            try:
                n = int(value)
            except ValueError:
                await llm_cmd.finish("用法：/llm context_limit <条数> | reset")
            if n < 1:
                await llm_cmd.finish("上下文上限须为正整数")
            svc.set_chat_history_limit(chat_id, n, chat_type=chat_type)
            await llm_cmd.finish(f"{scope_label}上下文上限已设为 {n} 条（/llm reload 可重置）")

        await llm_cmd.finish(
            "LLM 命令用法：/llm status|current|on|off|providers|probe|models [provider]|use <provider> [model]|"
            "personas|persona use <id>|trigger prefix <value>|trigger prefix_mode on|off|trigger at on|off|"
            "memory status|memory on|memory off|auto_memory on|off|reset|status|context_limit <n>|context_limit reset|clear_context|reload|mcp status"
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
            response = await SearXNGSearchClient().search(query, topic=topic, max_results=5)
        except WebSearchError as exc:
            await search_cmd.finish(f"联网搜索失败：{exc}")
        await search_cmd.finish(format_search_response(response))

    defectify_cmd = on_command("defectify", aliases={"故障化"}, priority=10, block=True)

    @defectify_cmd.handle()
    async def _(event):
        if not rate_limiter.allow("llm_chat", event.user_id):
            await defectify_cmd.finish("转写过于频繁，请稍后再试")

        _ensure_llm_bindings()
        svc = get_llm_service()

        rendered = render_message_for_llm(
            event.get_message(),
            bot_self_id=event.self_id,
            bot_self_ids={event.self_id},
            identity_index=svc.identities,
        )
        rendered_reply = render_reply_for_llm(
            getattr(event, "reply", None),
            bot_self_id=event.self_id,
            bot_self_ids={event.self_id},
            identity_index=svc.identities,
            include_image_placeholder=True,
        )
        prompt = _strip_leading_command_token(rendered.text)
        quoted_text = "" if rendered_reply is None else rendered_reply.text
        quoted_image_urls = [] if rendered_reply is None else rendered_reply.image_urls
        quoted_sender_name = "" if rendered_reply is None else rendered_reply.sender_name
        quoted_user_id = "" if rendered_reply is None else rendered_reply.user_id
        chat_type = _chat_type(event)
        chat_id = _chat_id(event)
        result = await svc.generate_defectify_reply(
            chat_id=chat_id,
            chat_type=chat_type,
            user_id=event.user_id,
            sender_name=get_sender_name(event),
            prompt=prompt,
            image_urls=rendered.image_urls,
            quoted_text=quoted_text,
            quoted_image_urls=quoted_image_urls,
            quoted_sender_name=quoted_sender_name,
            quoted_user_id=quoted_user_id,
        )
        if chat_type == "group":
            stats_tracker.record_trigger(event.group_id, result.get("rule_name", "unknown"))
        with bot_action_trace(
            trigger_kind="command",
            reason_code="command.defectify",
            reason_detail="命令触发：故障化转写",
            rule_name=result.get("rule_name", "defectify"),
            chat_type=chat_type,
            group_id=getattr(event, "group_id", ""),
            user_id=event.user_id,
            incoming_message_id=str(getattr(event, "message_id", "") or ""),
            incoming_preview=rendered.text,
            reply_preview=result["reply"],
            llm_used=bool(result.get("llm_used")),
            provider_id=str(result.get("provider_id", "")),
            model=str(result.get("model", "")),
            source="command.defectify",
        ):
            await defectify_cmd.finish(result["reply"])
