from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from time import time

from quickquip.adapters.nonebot.command_parts.common import _is_private_chat, _parse_profile_mode, _select_profile_samples, _strip_command_name
from quickquip.adapters.nonebot.long_messages import send_long_group_message
from quickquip.app.message_pipeline import _ensure_llm_bindings, daily_collector, get_llm_service, get_sender_identity_sources, group_quote_store, stats_tracker
from quickquip.chat.group_quotes import resolve_quote_display_name
from quickquip.llm.profile import generate_profile
from quickquip.llm.provider import LLMProviderError
from quickquip.llm.rendering import render_reply_for_llm


logger = logging.getLogger(__name__)


def _quote_display_name(group_id, quoted_user_id: str, snapshot_name: str) -> str:
    user_names, identity_index = get_sender_identity_sources(str(group_id))
    resolved, changed = resolve_quote_display_name(
        quoted_user_id, snapshot_name,
        user_names=user_names, identity_index=identity_index,
    )
    if changed:
        return f"{resolved} (原: {snapshot_name.strip()})"
    return resolved or "未知"


def _format_quote_rows(rows, group_id, header: str) -> str:
    lines = [header]
    for r in rows:
        preview = r["content"][:40] + ("…" if len(r["content"]) > 40 else "")
        display = _quote_display_name(group_id, r.get("quoted_user_id", ""), r["quoted_sender_name"])
        lines.append(f"#{r['group_seq']} 「{preview}」—— {display}")
    return "\n".join(lines)


def _resolve_sender_candidates(group_id, query: str) -> list[str]:
    """把名字反查成候选 QQ 号列表（stats 最新名片精确匹配 + 身份资料别名）。"""
    user_names, identity_index = get_sender_identity_sources(str(group_id))
    candidates: list[str] = []
    if user_names:
        candidates.extend(uid for uid, name in user_names.items() if name == query)
    if identity_index is not None:
        entry = identity_index.by_alias.get(query)
        if entry is not None:
            candidates.extend(str(qq) for qq in entry.qq_ids)
    return list(dict.fromkeys(candidates))


def register_history_commands(on_command, Message, MessageSegment) -> None:
    profile_cmd = on_command("profile", priority=10, block=True)

    @profile_cmd.handle()
    async def _(bot, event):
        if _is_private_chat(event):
            await profile_cmd.finish("该命令仅支持群聊")
        _ensure_llm_bindings()
        svc = get_llm_service()
        if not svc.config.is_available:
            await profile_cmd.finish("LLM 功能未启用，无法生成人物志")

        target_user_id = None
        for seg in event.get_message():
            seg_type = getattr(seg, "type", None)
            data = getattr(seg, "data", {})
            if seg_type == "at":
                qq = str(data.get("qq", "") or "").strip()
                if qq and qq != "all":
                    target_user_id = qq
                    break
        if not target_user_id:
            m = re.search(r"\[CQ:at,qq=(\d+)\]", str(event.get_message()))
            if m:
                target_user_id = m.group(1)
        if not target_user_id:
            await profile_cmd.finish("用法：/profile [short|middle|long|full] @某人")

        group_id = event.group_id
        profile_mode = _parse_profile_mode(str(event.get_message()))
        group_stats = stats_tracker.get_stats(group_id)
        target_name = group_stats.user_names.get(str(target_user_id), f"QQ:{target_user_id}")
        msg_count = group_stats.user_messages.get(str(target_user_id), 0)

        settings = svc.get_chat_settings(group_id, chat_type="group")
        provider_id = settings.provider_id or svc.config.runtime.default_provider or ""
        provider = svc.config.providers.get(provider_id)
        if not provider:
            await profile_cmd.finish("LLM provider 未配置")
        effective_model = settings.model or provider.default_model

        persona_id = settings.persona_id or svc.config.runtime.default_persona or ""
        persona = svc.config.personas.get(persona_id) if persona_id else None
        system_parts = []
        if persona:
            if persona.system_prompt:
                system_parts.append(persona.system_prompt)
            if persona.style_prompt:
                system_parts.append(persona.style_prompt)
        if provider.style_overrides:
            system_parts.append(provider.style_overrides)
        system_prompt = "\n\n".join(system_parts)

        now = time()
        try:
            memories_raw, all_msgs = await asyncio.gather(
                asyncio.to_thread(
                    svc.store.search_memories,
                    str(group_id),
                    user_id=str(target_user_id),
                    query=target_name,
                    limit=profile_mode.memory_limit,
                    scope="user",
                ),
                asyncio.to_thread(daily_collector.read_all, group_id)
                if profile_mode.full_records
                else asyncio.to_thread(
                    daily_collector.read_window,
                    group_id,
                    now - (profile_mode.read_days or 7) * 86400,
                    now,
                ),
            )
        except Exception:
            logger.exception("profile data collection failed for group=%s user=%s", group_id, target_user_id)
            await profile_cmd.finish("收集用户数据时出错，请稍后重试")

        memories = [m["content"] for m in memories_raw if m.get("content")]
        samples = _select_profile_samples(
            all_msgs,
            str(target_user_id),
            limit=profile_mode.sample_limit,
            max_chars=profile_mode.sample_max_chars,
        )

        await profile_cmd.send(f"正在生成 {target_name} 的{profile_mode.label}人物志，请稍候…")
        try:
            text, _ = await generate_profile(
                target_name=target_name,
                message_count=msg_count,
                memories=memories,
                recent_samples=samples,
                llm_config=svc.config,
                system_prompt=system_prompt,
                provider_id=provider.id,
                model=effective_model,
                profile_mode=profile_mode,
            )
        except LLMProviderError as exc:
            await profile_cmd.finish(f"人物志生成失败：{exc}")
        await send_long_group_message(
            bot,
            int(group_id),
            f"👤 {target_name}\n\n{text}",
            node_name="人物志",
            log_name="profile",
        )
        return

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
        _ensure_llm_bindings()
        svc = get_llm_service()
        group_id = event.group_id
        args = _strip_command_name(str(event.get_message()).strip(), "quote").strip()
        reply = getattr(event, "reply", None)

        # /quote random  or  /quote (no args, no reply) → random
        if args.lower() == "random" or (not args and not reply):
            q = group_quote_store.random(group_id)
            if q is None:
                await quote_cmd.finish("语录库还是空的，引用一条消息发 /quote 来收藏吧")
            ts = datetime.fromtimestamp(q["saved_at"]).strftime("%m-%d")
            seq_str = f"#{q.get('group_seq', '?')} " if q.get('group_seq') else ""
            display = _quote_display_name(group_id, q.get("quoted_user_id", ""), q["quoted_sender_name"])
            await quote_cmd.finish(f"{seq_str}「{q['content']}」\n—— {display} ({ts})")

        # /quote N  or  /quote #N → get by group_seq
        seq_match = re.match(r"^#?(\d+)$", args)
        if seq_match:
            seq = int(seq_match.group(1))
            q = group_quote_store.get_by_seq(group_id, seq)
            if q is None:
                await quote_cmd.finish(f"本群没有编号为 #{seq} 的语录")
            ts = datetime.fromtimestamp(q["saved_at"]).strftime("%m-%d")
            display = _quote_display_name(group_id, q.get("quoted_user_id", ""), q["quoted_sender_name"])
            await quote_cmd.finish(f"#{seq} 「{q['content']}」\n—— {display} ({ts})")

        # /quote search <keyword>  or  /quote s <keyword>
        search_match = re.match(r"^(?:search|s)\s+(.+)$", args, re.IGNORECASE)
        if search_match:
            keyword = search_match.group(1).strip()
            rows, total = group_quote_store.search(group_id, keyword, limit=10)
            if not rows:
                await quote_cmd.finish(f"未找到包含「{keyword}」的语录")
            await quote_cmd.finish(_format_quote_rows(rows, group_id, f"🔍 「{keyword}」（共 {total} 条）："))

        # /quote by <名字|QQ>  or  /quote b <名字|QQ> → by sender
        by_match = re.match(r"^(?:by|b)\s+(.+)$", args, re.IGNORECASE)
        if by_match:
            query = by_match.group(1).strip()
            is_qq = query.isdigit()
            user_ids = [query] if is_qq else _resolve_sender_candidates(group_id, query)
            rows, total = group_quote_store.search_by_sender(
                group_id,
                user_ids=user_ids,
                name_pattern="" if is_qq else query,
                limit=10,
            )
            if not rows:
                await quote_cmd.finish(f"未找到「{query}」发言的语录")
            await quote_cmd.finish(_format_quote_rows(rows, group_id, f"👤 「{query}」的语录（共 {total} 条）："))

        if not reply:
            await quote_cmd.finish(
                "用法：\n"
                "/quote — 随机一条\n"
                "/quote N — 查看编号为 N 的语录\n"
                "/quote search <关键词> — 搜索语录\n"
                "/quote by <名字|QQ> — 查看某人发言的语录\n"
                "引用消息 + /quote — 收藏语录"
            )
        rendered = render_reply_for_llm(
            reply,
            bot_self_id=event.self_id,
            bot_self_ids={event.self_id},
            identity_index=svc.identities,
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
