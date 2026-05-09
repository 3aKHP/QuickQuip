from __future__ import annotations

import random
import re

from quickquip.adapters.nonebot.command_parts.common import _evaluate_luck, _fence_luck_tips, _glue_luck_tips, _is_private_chat, _strip_command_name
from quickquip.app.message_pipeline import game_economy, niuniu_store
from quickquip.games.niuniu import fence_cd, fenced_cd, fencing, get_comment, glue_cd, gluing


def register_niuniu_commands(on_command, Message, MessageSegment) -> None:
    nn_register = on_command("注册牛牛", priority=10, block=True)

    @nn_register.handle()
    async def _(event):
        if _is_private_chat(event):
            await nn_register.finish("私聊不支持此命令")
        uid = str(event.user_id)
        if niuniu_store.exists(uid):
            length = niuniu_store.get_length(uid)
            await nn_register.finish(f"你已经有过牛牛啦！当前长度 {length} cm")
        length = niuniu_store.register(uid)
        if length > 0:
            await nn_register.finish(f"牛牛长出来啦！足足有 {length} cm 呢！")
        else:
            await nn_register.finish(
                f"牛牛长出来了？牛牛不见了！你是个可爱的女孩子！！深度足足有 {abs(length)} cm 呢！"
            )

    nn_unsubscribe = on_command("注销牛牛", priority=10, block=True)

    @nn_unsubscribe.handle()
    async def _(event):
        if _is_private_chat(event):
            await nn_unsubscribe.finish("私聊不支持此命令")
        uid = str(event.user_id)
        length = niuniu_store.get_length(uid)
        if length is None:
            await nn_unsubscribe.finish("你还没有牛牛呢！请发送 注册牛牛 领取你的牛牛！")
        balance = game_economy.get_balance(uid, str(event.group_id))
        if balance["gold"] < niuniu_store.config.unsubscribe_gold:
            await nn_unsubscribe.finish(
                f"你的金币不足 {niuniu_store.config.unsubscribe_gold}，无法注销牛牛！（当前 {balance['gold']} 金币）"
            )
        game_economy.deduct_gold(uid, str(event.group_id), niuniu_store.config.unsubscribe_gold)
        niuniu_store.unsubscribe(uid)
        await nn_unsubscribe.finish("从今往后你就没有牛牛啦！")

    nn_my = on_command("我的牛牛", priority=10, block=True)

    @nn_my.handle()
    async def _(event):
        if _is_private_chat(event):
            await nn_my.finish("私聊不支持此命令")
        uid = str(event.user_id)
        length = niuniu_store.get_length(uid)
        if length is None:
            await nn_my.finish("你还没有牛牛呢！请发送 注册牛牛 领取你的牛牛！")
        natural_rank = niuniu_store.get_rank_position(uid, "natural")
        if length > 0:
            rank_str = f"第 {natural_rank} 名"
        else:
            depth_rank = niuniu_store.get_rank_position(uid, "depth")
            abs_rank = niuniu_store.get_rank_position(uid, "absolute")
            rank_str = f"总榜第 {natural_rank} 名 | 深度榜第 {depth_rank} 名 | 绝对值榜第 {abs_rank} 名"
        last_glue = niuniu_store.latest_record_time(uid, "gluing")
        glue_luck = niuniu_store.get_glue_luck(uid)
        fence_luck = niuniu_store.get_fence_luck(uid)
        lines = [
            "🐂 我的牛牛",
            f"当前长度：{length} cm",
            f"排名：{rank_str}",
            f"打胶运势：{glue_luck}（{_evaluate_luck(glue_luck)}）",
            f"击剑运势：{fence_luck}（{_evaluate_luck(fence_luck)}）",
            f"最后打胶：{last_glue}",
            f"评价：{get_comment(length)}",
        ]
        await nn_my.finish("\n".join(lines))

    nn_glue = on_command("打胶", priority=10, block=True)

    @nn_glue.handle()
    async def _(event):
        if _is_private_chat(event):
            await nn_glue.finish("私聊不支持此命令")
        uid = str(event.user_id)
        remaining = glue_cd.check(uid)
        if remaining > 0:
            tips = [
                f"不行不行，你的身体会受不了的，歇 {int(remaining)}s 再来吧",
                f"休息一下吧，会炸膛的！{int(remaining)}s 后再来吧",
            ]
            await nn_glue.finish(random.choice(tips))
        msg, _ = gluing(niuniu_store, uid)
        await nn_glue.finish(msg)

    nn_fence = on_command("击剑", aliases={"jj", "JJ", "Jj", "jJ"}, priority=10, block=True)

    @nn_fence.handle()
    async def _(event):
        if _is_private_chat(event):
            await nn_fence.finish("私聊不支持此命令")
        uid = str(event.user_id)

        # CD check
        remaining = fence_cd.check(uid)
        if remaining > 0:
            tips = [
                f"不行不行，你的身体会受不了的，歇 {int(remaining)}s 再来吧",
                f"你这种男同就应该被送去集中营！等待 {int(remaining)}s 再来吧",
                f"打咩哟！你的牛牛会炸的，休息 {int(remaining)}s 再来吧",
            ]
            await nn_fence.finish(random.choice(tips))

        # Extract @target — prefer raw_message (preserves self-@ that
        # get_message segments may strip), fall back to segment parsing.
        target_uid = None
        raw = getattr(event, "raw_message", None) or str(event.get_message())
        m = re.search(r"\[CQ:at,qq=(\d+)\]", raw)
        if m:
            target_uid = m.group(1)
        if not target_uid:
            for seg in event.get_message():
                seg_type = getattr(seg, "type", None)
                data = getattr(seg, "data", {})
                if seg_type == "at":
                    qq = str(data.get("qq", "") or "").strip()
                    if qq and qq != "all":
                        target_uid = qq
                        break
        if not target_uid:
            await nn_fence.finish("你要和谁击剑？请 @一位用户")

        if target_uid == uid:
            await nn_fence.finish("不能和自己击剑哦！")

        # Check defender CD
        remaining = fenced_cd.check(target_uid)
        if remaining > 0:
            tips = [
                f"对方刚被击剑过，需要休息 {int(remaining)}s 才能再次被击剑",
                f"对方牛牛还在恢复中，{int(remaining)}s 后再来吧",
            ]
            await nn_fence.finish(random.choice(tips))

        is_vs_bot = (target_uid == str(event.self_id))
        result = fencing(niuniu_store, uid, target_uid, oppo_is_bot=is_vs_bot)
        await nn_fence.finish(result)

    def _build_rank_text(entries: list[dict], title: str, unit: str = "cm") -> str:
        if not entries:
            return f"{title}\n暂无数据…"
        lines = [f"🏆 {title}："]
        for i, e in enumerate(entries, 1):
            lines.append(f"{i}. QQ:{e['uid']} — {e['length']} {unit}")
        return "\n".join(lines)

    nn_len_rank = on_command("牛牛长度排行", priority=10, block=True)

    @nn_len_rank.handle()
    async def _(event):
        if _is_private_chat(event):
            await nn_len_rank.finish("私聊不支持此命令，请使用 牛牛长度总排行")
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "牛牛长度排行").strip()
        n = int(args) if args.isdigit() else 10
        n = min(n, 50)
        entries = niuniu_store.rank_by_length(limit=n)
        await nn_len_rank.finish(_build_rank_text(entries, "牛牛长度排行"))

    nn_len_rank_all = on_command("牛牛长度总排行", priority=10, block=True)

    @nn_len_rank_all.handle()
    async def _(event):
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "牛牛长度总排行").strip()
        n = int(args) if args.isdigit() else 10
        n = min(n, 50)
        entries = niuniu_store.rank_by_length(limit=n)
        await nn_len_rank_all.finish(_build_rank_text(entries, "牛牛长度总排行（全局）"))

    nn_depth_rank = on_command("牛牛深度排行", priority=10, block=True)

    @nn_depth_rank.handle()
    async def _(event):
        if _is_private_chat(event):
            await nn_depth_rank.finish("私聊不支持此命令，请使用 牛牛深度总排行")
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "牛牛深度排行").strip()
        n = int(args) if args.isdigit() else 10
        n = min(n, 50)
        entries = niuniu_store.rank_by_depth(limit=n)
        await nn_depth_rank.finish(_build_rank_text(entries, "牛牛深度排行"))

    nn_depth_rank_all = on_command("牛牛深度总排行", priority=10, block=True)

    @nn_depth_rank_all.handle()
    async def _(event):
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "牛牛深度总排行").strip()
        n = int(args) if args.isdigit() else 10
        n = min(n, 50)
        entries = niuniu_store.rank_by_depth(limit=n)
        await nn_depth_rank_all.finish(_build_rank_text(entries, "牛牛深度总排行（全局）"))

    nn_natural_rank = on_command("牛牛总排行", priority=10, block=True)

    @nn_natural_rank.handle()
    async def _(event):
        if _is_private_chat(event):
            await nn_natural_rank.finish("私聊不支持此命令")
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "牛牛总排行").strip()
        n = int(args) if args.isdigit() else 10
        n = min(n, 50)
        entries = niuniu_store.rank_by_natural(limit=n)
        await nn_natural_rank.finish(_build_rank_text(entries, "牛牛总排行（自然数值）"))

    nn_abs_rank = on_command("牛牛绝对值排行", priority=10, block=True)

    @nn_abs_rank.handle()
    async def _(event):
        if _is_private_chat(event):
            await nn_abs_rank.finish("私聊不支持此命令，请使用 牛牛绝对值总排行")
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "牛牛绝对值排行").strip()
        n = int(args) if args.isdigit() else 10
        n = min(n, 50)
        entries = niuniu_store.rank_by_absolute(limit=n)
        await nn_abs_rank.finish(_build_rank_text(entries, "牛牛绝对值排行"))

    nn_abs_rank_all = on_command("牛牛绝对值总排行", priority=10, block=True)

    @nn_abs_rank_all.handle()
    async def _(event):
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "牛牛绝对值总排行").strip()
        n = int(args) if args.isdigit() else 10
        n = min(n, 50)
        entries = niuniu_store.rank_by_absolute(limit=n)
        await nn_abs_rank_all.finish(_build_rank_text(entries, "牛牛绝对值总排行（全局）"))

    nn_records = on_command("我的牛牛战绩", priority=10, block=True)

    @nn_records.handle()
    async def _(event):
        if _is_private_chat(event):
            await nn_records.finish("私聊不支持此命令")
        uid = str(event.user_id)
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "我的牛牛战绩").strip()
        n = int(args) if args.isdigit() else 10
        n = min(n, 50)
        records = niuniu_store.get_records(uid, limit=n)
        if not records:
            await nn_records.finish("你还没有任何牛牛战绩哦~")
        action_labels = {
            "register": "📝 注册",
            "unsubscribe": "❌ 注销",
            "gluing": "💦 打胶",
            "fencing": "⚔️ 击剑（主动）",
            "fenced": "🎯 被击剑",
            "fencing_draw": "🤝 击剑平局",
            "fencing_self_hurt": "💨 击剑自伤",
        }
        lines = ["📋 我的牛牛战绩："]
        for r in records:
            act = action_labels.get(r["action"], r["action"])
            diff = r["diff"]
            sign = "+" if diff > 0 else ""
            lines.append(f"{act} | {r['origin_length']} → {r['new_length']} ({sign}{diff}) | {r['created_at']}")
        await nn_records.finish("\n".join(lines))

    nn_glue_luck = on_command("打胶运势", priority=10, block=True)

    @nn_glue_luck.handle()
    async def _(event):
        if _is_private_chat(event):
            await nn_glue_luck.finish("私聊不支持此命令")
        uid = str(event.user_id)
        if not niuniu_store.exists(uid):
            await nn_glue_luck.finish("你还没有牛牛呢！请先发送 注册牛牛")
        luck = niuniu_store.get_glue_luck(uid)
        label = _evaluate_luck(luck)
        tips = _glue_luck_tips(luck)
        await nn_glue_luck.finish(
            f"🔮 今日打胶运势\n运势值：{luck}\n评价：{label}\n{tips}"
        )

    nn_fence_luck = on_command("击剑运势", priority=10, block=True)

    @nn_fence_luck.handle()
    async def _(event):
        if _is_private_chat(event):
            await nn_fence_luck.finish("私聊不支持此命令")
        uid = str(event.user_id)
        if not niuniu_store.exists(uid):
            await nn_fence_luck.finish("你还没有牛牛呢！请先发送 注册牛牛")
        luck = niuniu_store.get_fence_luck(uid)
        label = _evaluate_luck(luck)
        tips = _fence_luck_tips(luck)
        await nn_fence_luck.finish(
            f"⚔️ 今日击剑运势\n运势值：{luck}\n评价：{label}\n{tips}"
        )
