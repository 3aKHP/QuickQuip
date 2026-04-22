from __future__ import annotations

import asyncio
import hashlib
import random
import re
import shlex
from datetime import date, datetime
from time import time

from quickquip.app.message_pipeline import RULE_SWITCH_PATH, STATS_PATH, daily_collector, get_sender_name, group_quote_store, llm_service, offline_message_store, rate_limiter, reload_chat_rules_pipeline, rule_switch, stats_tracker
from quickquip.app.message_pipeline import is_admin as _is_admin
from quickquip.app.message_pipeline import strip_command_name as _strip_command_name
from quickquip.llm.image_gen import generate_image
from quickquip.llm.provider import LLMProviderError
from quickquip.llm.rendering import render_message_for_llm, render_reply_for_llm
from quickquip.search.web_search import WebSearchError, build_search_client, format_search_response
from quickquip.tieba.config import TIEBA_RULE_NAME
from quickquip.tieba.errors import TiebaLoginRequiredError, TiebaServiceError
from quickquip.tieba.service import tieba_service


def _is_private_chat(event) -> bool:
    return getattr(event, "message_type", "") == "private" or getattr(event, "group_id", None) is None


def _chat_type(event) -> str:
    return "private" if _is_private_chat(event) else "group"


def _chat_id(event):
    if _is_private_chat(event):
        return event.user_id
    return event.group_id


def _chat_label(event) -> str:
    return "当前私聊" if _is_private_chat(event) else "本群"


def _allow_scope_management(event) -> bool:
    return _is_private_chat(event) or _is_admin(event)


_PRESET_RE = re.compile(r'--preset\s+(?:"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'|(\S.*))', re.DOTALL)
_RESUME_RE = re.compile(r'--resume(?:\s+(\d+))?')
_DICE_RE = re.compile(r"^(\d*)[dD](\d+)$")

_FORTUNES = [
    ("大吉", "财运亨通，诸事大顺，今日宜出行、宜交友"),
    ("吉", "今日顺遂，保持当下状态即可"),
    ("中吉", "稳中求进，努力终有回报"),
    ("小吉", "小有收获，量力而行，不必强求"),
    ("末吉", "平稳即福，顺势而为，随心所欲"),
    ("平", "波澜不惊，平常心是最贵的"),
    ("小凶", "遇事三思而后行，不宜冒进"),
    ("凶", "今日多有阻碍，静待时机，勿急于求成"),
]
_NUMBER_EMOJIS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣")


def _daily_fortune(user_id: int | str) -> tuple[str, str]:
    h = int(hashlib.md5(f"{user_id}:{date.today().isoformat()}".encode()).hexdigest(), 16)
    return _FORTUNES[h % len(_FORTUNES)]


def _safe_shlex_split(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _parse_preset(args: str) -> str:
    m = _PRESET_RE.search(args)
    if not m:
        return ""
    return (m.group(1) or m.group(2) or m.group(3) or "").strip()


def _parse_resume(args: str) -> tuple[bool, int | None]:
    m = _RESUME_RE.search(args)
    if not m:
        return False, None
    num_str = m.group(1)
    return True, int(num_str) if num_str else None


def _parse_tieba_command_args(args: str) -> tuple[str, str | None, bool]:
    normalized_args = args.strip()
    if not normalized_args:
        return "random", None, False

    tokens = normalized_args.split()
    head = tokens[0].lower()
    remainder = normalized_args[len(tokens[0]):].strip()

    if head in {"random", "status", "refresh", "source"}:
        return head, remainder or None, False
    if head == "text":
        return "random", remainder or None, True
    if head == "list":
        return "status", None, False
    return "random", normalized_args, False


def _strip_leading_command_token(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        return ""
    parts = normalized.split(maxsplit=1)
    if len(parts) == 1:
        return ""
    return parts[1].strip()


def register_commands(on_command, Message, MessageSegment) -> None:
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

    llm_cmd = on_command("llm", priority=10, block=True)

    @llm_cmd.handle()
    async def _(event):
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "llm")
        chat_type = _chat_type(event)
        chat_id = _chat_id(event)
        scope_label = _chat_label(event)
        tokens = args.split()

        if not args or args == "status":
            await llm_cmd.finish(llm_service.format_status(chat_id, chat_type=chat_type))

        if args == "current":
            await llm_cmd.finish(llm_service.format_current(chat_id, chat_type=chat_type))

        if args in {"mcp", "mcp status"}:
            await llm_cmd.finish(llm_service.format_mcp_status())

        if args == "mcp reload":
            if not _allow_scope_management(event):
                await llm_cmd.finish("仅管理员可执行此操作")
            await llm_cmd.send("正在拉取 MCP 镜像并重连，请稍候…")
            await llm_service.reload_mcp(background=False)
            await llm_cmd.finish(llm_service.format_mcp_status())

        if args == "providers":
            await llm_cmd.finish(llm_service.format_providers())

        if args == "personas":
            await llm_cmd.finish(llm_service.format_personas(chat_type=chat_type))

        if tokens[:1] == ["models"]:
            provider_id = tokens[1] if len(tokens) > 1 else None
            await llm_cmd.finish(llm_service.format_models(provider_id))

        if tokens[:2] == ["memory", "status"]:
            await llm_cmd.finish(llm_service.format_memory_status(chat_id, chat_type=chat_type))

        if not _allow_scope_management(event):
            await llm_cmd.finish("仅管理员可执行此操作")

        if tokens[:1] == ["on"]:
            if chat_type == "private":
                has_resume, resume_num = _parse_resume(args)
                if has_resume:
                    result = llm_service.resume_private_session(chat_id, resume_num)
                    if "error" in result:
                        await llm_cmd.finish(result["error"])
                    preset_override = _parse_preset(args)
                    if preset_override:
                        scope_key = llm_service.build_chat_scope_key(chat_id, "private")
                        llm_service._session_presets[scope_key] = preset_override
                    preset = preset_override or result.get("preset", "")
                    msg = f"已恢复存档 #{result['archive_number']}（{result['message_count']} 条消息）"
                    if preset:
                        preview = preset[:80] + ("..." if len(preset) > 80 else "")
                        msg += f"\n附加设定：{preview}"
                    await llm_cmd.finish(msg)
                preset = _parse_preset(args)
                llm_service.start_private_session(chat_id, preset=preset)
                msg = f"{scope_label}会话已开启。也可以直接使用 /start_sesssion，当前上下文上限为 {llm_service.get_default_history_limit('private')} 条。"
                if preset:
                    preview = preset[:80] + ("..." if len(preset) > 80 else "")
                    msg += f"\n附加设定：{preview}"
                await llm_cmd.finish(msg)
            else:
                llm_service.set_chat_enabled(chat_id, True, chat_type=chat_type)
                await llm_cmd.finish(f"{scope_label} LLM 已开启")

        if tokens[:1] == ["off"]:
            if chat_type == "private":
                no_save = "--no-save" in args
                result = llm_service.end_private_session(chat_id, save=not no_save)
                deleted = result["deleted"]
                archive_number = result.get("archive_number")
                if archive_number is not None:
                    await llm_cmd.finish(f"{scope_label}会话已结束，已存档为 #{archive_number}（{deleted} 条消息）。")
                else:
                    suffix = "（未存档）" if no_save else ""
                    await llm_cmd.finish(f"{scope_label}会话已结束，并清空了 {deleted} 条短期上下文。{suffix}")
            else:
                llm_service.set_chat_enabled(chat_id, False, chat_type=chat_type)
                await llm_cmd.finish(f"{scope_label} LLM 已关闭")

        if args == "reload":
            llm_service.reset_chat_history_limit(chat_id, chat_type=chat_type)
            config = await llm_service.reload_runtime(background=True)
            if config.load_error:
                await llm_cmd.finish(f"LLM 配置重载失败：{config.load_error}")
            await llm_cmd.finish("LLM 配置已重载")

        if args == "clear_context":
            deleted = llm_service.clear_context(chat_id, chat_type=chat_type)
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
            scope_key = llm_service.build_chat_scope_key(chat_id, chat_type)
            deleted = llm_service.delete_message_from_context(scope_key, target_msg_id)
            if deleted:
                await llm_cmd.finish(f"已从上下文中删除消息 {target_msg_id}")
            else:
                await llm_cmd.finish(f"未找到消息 {target_msg_id}，可能已过期或未被记录")

        if tokens[:1] == ["use"] and len(tokens) >= 2:
            provider_id = tokens[1]
            model = tokens[2] if len(tokens) >= 3 else ""
            try:
                resolved = llm_service.set_chat_model(chat_id, provider_id, model, chat_type=chat_type)
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
                llm_service.set_chat_persona(chat_id, persona_id, chat_type=chat_type)
            except ValueError as exc:
                await llm_cmd.finish(str(exc))
            await llm_cmd.finish(f"{scope_label}人格已切换到 {persona_id}")

        if tokens[:2] == ["trigger", "prefix"] and len(tokens) >= 3:
            try:
                llm_service.set_chat_trigger_prefix(chat_id, tokens[2], chat_type=chat_type)
            except ValueError as exc:
                await llm_cmd.finish(str(exc))
            await llm_cmd.finish(f"{scope_label}触发前缀已改为 {tokens[2]}")

        if tokens[:2] == ["trigger", "prefix_mode"] and len(tokens) >= 3:
            value = tokens[2].lower()
            if value not in {"on", "off"}:
                await llm_cmd.finish("用法：/llm trigger prefix_mode on|off")
            llm_service.set_chat_allow_prefix(chat_id, value == "on", chat_type=chat_type)
            await llm_cmd.finish(f"{scope_label}前缀触发已设为 {value}")

        if tokens[:2] == ["trigger", "at"] and len(tokens) >= 3:
            if chat_type == "private":
                await llm_cmd.finish("私聊仅支持前缀触发，不支持艾特触发")
            value = tokens[2].lower()
            if value not in {"on", "off"}:
                await llm_cmd.finish("用法：/llm trigger at on|off")
            llm_service.set_group_allow_at(chat_id, value == "on")
            await llm_cmd.finish(f"{scope_label}艾特触发已设为 {value}")

        if tokens[:2] == ["memory", "on"]:
            llm_service.set_chat_memory_enabled(chat_id, True, chat_type=chat_type)
            await llm_cmd.finish(f"{scope_label}记忆注入已开启")

        if tokens[:2] == ["memory", "off"]:
            llm_service.set_chat_memory_enabled(chat_id, False, chat_type=chat_type)
            await llm_cmd.finish(f"{scope_label}记忆注入已关闭")

        if tokens[:1] == ["auto_memory"] and len(tokens) >= 2:
            sub = tokens[1].lower()
            if sub == "on":
                llm_service.set_chat_auto_memory_enabled(chat_id, True, chat_type=chat_type)
                await llm_cmd.finish(f"{scope_label}自动记忆抽取已开启")
            if sub == "off":
                llm_service.set_chat_auto_memory_enabled(chat_id, False, chat_type=chat_type)
                await llm_cmd.finish(f"{scope_label}自动记忆抽取已关闭")
            if sub == "reset":
                llm_service.set_chat_auto_memory_enabled(chat_id, None, chat_type=chat_type)
                default = "开" if llm_service.config.runtime.auto_memory_enabled else "关"
                await llm_cmd.finish(f"{scope_label}自动记忆抽取已跟随全局默认（当前：{default}）")
            if sub == "status":
                settings = llm_service.get_chat_settings(chat_id, chat_type=chat_type)
                default = "开" if llm_service.config.runtime.auto_memory_enabled else "关"
                current = "开" if settings.auto_memory_enabled else "关"
                await llm_cmd.finish(
                    f"{scope_label}自动记忆抽取：{current}（全局默认 {default}）"
                )

        if tokens[:1] == ["context_limit"] and len(tokens) >= 2:
            value = tokens[1].lower()
            if value in {"reset", "off"}:
                llm_service.reset_chat_history_limit(chat_id, chat_type=chat_type)
                await llm_cmd.finish(
                    f"{scope_label}上下文上限已重置为默认（{llm_service.get_default_history_limit(chat_type)} 条）"
                )
            try:
                n = int(value)
            except ValueError:
                await llm_cmd.finish("用法：/llm context_limit <条数> | reset")
            if n < 1:
                await llm_cmd.finish("上下文上限须为正整数")
            llm_service.set_chat_history_limit(chat_id, n, chat_type=chat_type)
            await llm_cmd.finish(f"{scope_label}上下文上限已设为 {n} 条（/llm reload 可重置）")

        await llm_cmd.finish(
            "LLM 命令用法：/llm status|current|on|off|providers|models [provider]|use <provider> [model]|"
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
            response = await build_search_client().search(query, topic=topic, max_results=5)
        except WebSearchError as exc:
            await search_cmd.finish(f"联网搜索失败：{exc}")
        await search_cmd.finish(format_search_response(response))

    defectify_cmd = on_command("defectify", aliases={"故障化"}, priority=10, block=True)

    @defectify_cmd.handle()
    async def _(event):
        if not rate_limiter.allow("llm_chat", event.user_id):
            await defectify_cmd.finish("转写过于频繁，请稍后再试")

        rendered = render_message_for_llm(
            event.get_message(),
            bot_self_id=event.self_id,
            identity_index=llm_service.identities,
        )
        rendered_reply = render_reply_for_llm(
            getattr(event, "reply", None),
            bot_self_id=event.self_id,
            identity_index=llm_service.identities,
            include_image_placeholder=True,
        )
        prompt = _strip_leading_command_token(rendered.text)
        quoted_text = "" if rendered_reply is None else rendered_reply.text
        quoted_image_urls = [] if rendered_reply is None else rendered_reply.image_urls
        quoted_sender_name = "" if rendered_reply is None else rendered_reply.sender_name
        quoted_user_id = "" if rendered_reply is None else rendered_reply.user_id
        chat_type = _chat_type(event)
        chat_id = _chat_id(event)
        result = await llm_service.generate_defectify_reply(
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
        await defectify_cmd.finish(result["reply"])

    draw_cmd = on_command("draw", priority=10, block=True)

    @draw_cmd.handle()
    async def _(event):
        if not rate_limiter.allow("image_gen", event.user_id):
            await draw_cmd.finish("图片生成过于频繁，请稍后再试")
        ig = llm_service.config.image_generation
        if not ig.enabled:
            await draw_cmd.finish("图片生成功能未启用")
        provider = llm_service.config.providers.get(ig.provider_id)
        if provider is None:
            await draw_cmd.finish("图片生成 provider 未配置")
        text = str(event.get_message()).strip()
        prompt = _strip_command_name(text, "draw").strip()
        if not prompt:
            await draw_cmd.finish("用法：/draw <描述>")
        await draw_cmd.send("正在生成图片，请稍候…")
        try:
            image_b64 = await generate_image(ig, provider, prompt)
        except LLMProviderError as exc:
            await draw_cmd.finish(f"图片生成失败：{exc}")
        await draw_cmd.finish(Message([MessageSegment.image(f"base64://{image_b64}")]))

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



    @reset_stats_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await reset_stats_cmd.finish("私聊不支持 /reset_stats")
        if not _is_admin(event):
            await reset_stats_cmd.finish("仅管理员可执行此操作")
        stats_tracker.reset(event.group_id)
        stats_tracker.save(STATS_PATH)
        await reset_stats_cmd.finish("统计数据已重置")

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

    remember_cmd = on_command("remember", priority=10, block=True)

    @remember_cmd.handle()
    async def _(event):
        if not _allow_scope_management(event):
            await remember_cmd.finish("仅管理员可执行此操作")
        content = _strip_command_name(str(event.get_message()).strip(), "remember")
        if not content:
            await remember_cmd.finish("用法：/remember <要保存的记忆>")
        chat_type = _chat_type(event)
        chat_id = _chat_id(event)
        memory_id = llm_service.remember_memory(chat_id, content, chat_type=chat_type)
        await remember_cmd.finish(f"已写入{_chat_label(event)}记忆 #{memory_id}")

    memories_cmd = on_command("memories", priority=10, block=True)

    @memories_cmd.handle()
    async def _(event):
        keyword = _strip_command_name(str(event.get_message()).strip(), "memories")
        reply = llm_service.format_memories(_chat_id(event), keyword=keyword or None, chat_type=_chat_type(event))
        await memories_cmd.finish(reply)

    forget_cmd = on_command("forget", priority=10, block=True)

    @forget_cmd.handle()
    async def _(event):
        if not _allow_scope_management(event):
            await forget_cmd.finish("仅管理员可执行此操作")
        keyword = _strip_command_name(str(event.get_message()).strip(), "forget")
        if not keyword:
            await forget_cmd.finish("用法：/forget <关键词>")
        deleted = llm_service.forget_memories(_chat_id(event), keyword, chat_type=_chat_type(event))
        await forget_cmd.finish(f"已删除{_chat_label(event)}中的 {deleted} 条记忆")

    forget_all_cmd = on_command("forget_all", priority=10, block=True)

    @forget_all_cmd.handle()
    async def _(event):
        if not _allow_scope_management(event):
            await forget_all_cmd.finish("仅管理员可执行此操作")
        deleted = llm_service.clear_memories(_chat_id(event), chat_type=_chat_type(event))
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

    roll_cmd = on_command("roll", priority=10, block=True)

    @roll_cmd.handle()
    async def _(event):
        args = _strip_command_name(str(event.get_message()).strip(), "roll").strip() or "1d6"
        m = _DICE_RE.match(args)
        if not m:
            await roll_cmd.finish("用法：/roll [NdM]，例如 /roll 2d6 /roll d20")
        n = int(m.group(1) or 1)
        sides = int(m.group(2))
        if not 1 <= n <= 10:
            await roll_cmd.finish("骰子数量须在 1~10 之间")
        if not 2 <= sides <= 1000:
            await roll_cmd.finish("面数须在 2~1000 之间")
        results = [random.randint(1, sides) for _ in range(n)]
        if n == 1:
            await roll_cmd.finish(f"🎲 {results[0]}")
        detail = " + ".join(str(r) for r in results)
        await roll_cmd.finish(f"🎲 {detail} = {sum(results)}")

    choose_cmd = on_command("choose", priority=10, block=True)

    @choose_cmd.handle()
    async def _(event):
        args = _strip_command_name(str(event.get_message()).strip(), "choose").strip()
        if not args:
            await choose_cmd.finish("用法：/choose A B C")
        try:
            options = _safe_shlex_split(args)
        except ValueError:
            options = args.split()
        if len(options) < 2:
            await choose_cmd.finish("至少需要两个选项")
        await choose_cmd.finish(f"选择了：{random.choice(options)}")

    fortune_cmd = on_command("fortune", priority=10, block=True)

    @fortune_cmd.handle()
    async def _(event):
        grade, desc = _daily_fortune(event.user_id)
        await fortune_cmd.finish(f"今日运势：{grade}\n{desc}")

    vote_cmd = on_command("vote", priority=10, block=True)

    @vote_cmd.handle()
    async def _(event):
        args = _strip_command_name(str(event.get_message()).strip(), "vote").strip()
        if not args:
            await vote_cmd.finish('用法：/vote "议题" 选项A 选项B ...')
        try:
            parts = _safe_shlex_split(args)
        except ValueError:
            parts = args.split()
        if len(parts) < 3:
            await vote_cmd.finish('用法：/vote "议题" 选项A 选项B（至少两个选项）')
        topic, options = parts[0], parts[1:]
        if len(options) > 9:
            await vote_cmd.finish("选项最多 9 个")
        lines = [f"📊 {topic}"]
        for i, opt in enumerate(options):
            lines.append(f"{_NUMBER_EMOJIS[i]} {opt}")
        await vote_cmd.finish("\n".join(lines))

    find_cmd = on_command("find", priority=10, block=True)

    @find_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await find_cmd.finish("该命令仅支持群聊")
        keyword = _strip_command_name(str(event.get_message()).strip(), "find").strip()
        if not keyword:
            await find_cmd.finish("用法：/find <关键词>")
        group_id = event.group_id
        now = time()
        messages = await asyncio.to_thread(
            daily_collector.read_window, group_id, now - 30 * 86400, now
        )
        kw_lower = keyword.lower()
        hits = [m for m in messages if kw_lower in m.get("text", "").lower()]
        if not hits:
            await find_cmd.finish(f"没有找到包含「{keyword}」的消息（最近 30 天）")
        shown = hits[-5:]
        header = f"找到 {len(hits)} 条，显示最新 5 条：" if len(hits) > 5 else f"找到 {len(hits)} 条："
        lines = [header]
        for m in shown:
            ts = datetime.fromtimestamp(m["ts"]).strftime("%m-%d %H:%M")
            text = m.get("text", "")
            if len(text) > 50:
                text = text[:50] + "…"
            lines.append(f"[{ts}] {m['sender']}: {text}")
        await find_cmd.finish("\n".join(lines))

    quote_cmd = on_command("quote", priority=10, block=True)

    @quote_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await quote_cmd.finish("该命令仅支持群聊")
        group_id = event.group_id
        args = _strip_command_name(str(event.get_message()).strip(), "quote").strip()
        reply = getattr(event, "reply", None)
        if args.lower() == "random" or (not args and not reply):
            q = group_quote_store.random(group_id)
            if q is None:
                await quote_cmd.finish("语录库还是空的，引用一条消息发 /quote 来收藏吧")
            ts = datetime.fromtimestamp(q["saved_at"]).strftime("%m-%d")
            await quote_cmd.finish(f"「{q['content']}」\n—— {q['quoted_sender_name']} ({ts})")
        if not reply:
            await quote_cmd.finish("用法：引用一条消息后发 /quote 收藏；/quote random 随机一条")
        rendered = render_reply_for_llm(
            reply,
            bot_self_id=event.self_id,
            identity_index=llm_service.identities,
        )
        if not rendered or not rendered.text.strip():
            await quote_cmd.finish("引用的消息没有文字内容，无法收藏")
        content = rendered.text.strip()
        if len(content) > 500:
            await quote_cmd.finish("内容过长（限 500 字），无法收藏")
        group_quote_store.add(
            group_id=group_id,
            quoted_user_id=rendered.user_id or "",
            quoted_sender_name=rendered.sender_name or "未知",
            content=content,
            saved_by_user_id=event.user_id,
        )
        total = group_quote_store.count(group_id)
        preview = content[:30] + ("…" if len(content) > 30 else "")
        await quote_cmd.finish(f"已收藏「{preview}」（本群共 {total} 条语录）")

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
