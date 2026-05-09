from __future__ import annotations

from quickquip.adapters.nonebot.command_parts.common import _is_private_chat, _strip_command_name
from quickquip.app.message_pipeline import game_economy, game_registry, game_scores


def register_games_commands(on_command, Message, MessageSegment) -> None:
    game_cmd = on_command("game", priority=10, block=True)

    @game_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await game_cmd.finish("该命令仅支持群聊")
        group_id = str(event.group_id)
        text = str(event.get_message()).strip()
        args = _strip_command_name(text, "game").strip()
        tokens = args.split()
        sub = tokens[0].lower() if tokens else ""

        if sub == "list":
            games = game_registry.list_games()
            if not games:
                await game_cmd.finish("暂无可用游戏")
            lines = ["可用游戏："]
            for g in games:
                aliases_str = f"（别名：{'、'.join(g['aliases'])}）" if g["aliases"] else ""
                lines.append(f"- {g['name']} {aliases_str}")
            await game_cmd.finish("\n".join(lines))

        if sub == "start":
            raw_args = args[len(tokens[0]):].strip() if len(tokens) > 1 else ""
            if not raw_args:
                await game_cmd.finish("用法：/game start <游戏名>，使用 /game list 查看可用游戏")
            # Split into game name and optional argument (e.g. "21点 500" → "21点", "500")
            parts = raw_args.split(maxsplit=1)
            game_name = parts[0]
            start_arg = parts[1] if len(parts) > 1 else ""
            game = game_registry.find(game_name)
            if game is None:
                await game_cmd.finish(f"未找到游戏：{game_name}，使用 /game list 查看可用游戏")
            active_name = game_registry.get_active_game_name(group_id)
            if active_name:
                await game_cmd.finish(f"本群已有进行中的游戏：{active_name}，请先 /game stop 结束")
            opening = game_registry.start_game(group_id, str(event.user_id), game, start_arg=start_arg)
            if opening is None:
                await game_cmd.finish(f"本群已有进行中的游戏：{game_registry.get_active_game_name(group_id)}，请先 /game stop 结束")
            await game_cmd.finish(opening)

        if sub == "stop":
            active_name = game_registry.get_active_game_name(group_id)
            if not active_name:
                await game_cmd.finish("本群没有进行中的游戏")
            closing = game_registry.stop_game(group_id)
            if closing is None:
                await game_cmd.finish(f"无法结束游戏：{active_name}")
            await game_cmd.finish(closing)

        if sub == "score":
            game_name = args[len(tokens[0]):].strip() if len(tokens) > 1 else ""
            if not game_name:
                await game_cmd.finish("用法：/game score <游戏名>，使用 /game list 查看可用游戏")
            game = game_registry.find(game_name)
            if game is None:
                await game_cmd.finish(f"未找到游戏：{game_name}，使用 /game list 查看可用游戏")
            leaderboard = game_scores.get_leaderboard(group_id, game.name, top_n=10)
            if not leaderboard:
                await game_cmd.finish(f"{game.name} 暂无排行数据")
            lines = [f"{game.name} 排行榜（前 {len(leaderboard)} 名）："]
            for i, (uid, score) in enumerate(leaderboard, 1):
                lines.append(f"{i}. QQ:{uid} — {score} 胜")
            await game_cmd.finish("\n".join(lines))

        # No valid subcommand
        await game_cmd.finish(
            "游戏命令用法：\n"
            "/game list — 查看可用游戏\n"
            "/game start <游戏名> — 开始游戏\n"
            "/game stop — 结束当前游戏\n"
            "/game score <游戏名> — 查看排行榜"
        )

    sign_cmd = on_command("sign", aliases={"签到"}, priority=10, block=True)

    @sign_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await sign_cmd.finish("私聊不支持签到")
        result = game_economy.sign_in(str(event.user_id), str(event.group_id))
        lines = [
            result["message"],
            f"金币：{result['total_gold']} | 好感度：{result['total_affection']}",
        ]
        if result["streak"] > 1:
            lines.append(f"连续签到：{result['streak']} 天")
        await sign_cmd.finish("\n".join(lines))

    gold_cmd = on_command("gold", aliases={"金币", "我的"}, priority=10, block=True)

    @gold_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await gold_cmd.finish("私聊不支持此命令")
        balance = game_economy.get_balance(str(event.user_id), str(event.group_id))
        lines = [
            f"💰 金币：{balance['gold']}",
            f"💗 好感度：{balance['affection']}",
            f"🔥 连续签到：{balance['sign_streak']} 天",
        ]
        await gold_cmd.finish("\n".join(lines))

    gold_rank_cmd = on_command("gold_rank", aliases={"金币排行"}, priority=10, block=True)

    @gold_rank_cmd.handle()
    async def _(event):
        if _is_private_chat(event):
            await gold_rank_cmd.finish("私聊不支持此命令")
        rank = game_economy.get_rank(str(event.group_id), top_n=10)
        if not rank:
            await gold_rank_cmd.finish("本群暂无金币数据，快去签到吧！")
        lines = ["🏆 本群金币排行："]
        for i, entry in enumerate(rank, 1):
            lines.append(f"{i}. QQ:{entry['user_id']} — {entry['gold']} 💰")
        await gold_rank_cmd.finish("\n".join(lines))
