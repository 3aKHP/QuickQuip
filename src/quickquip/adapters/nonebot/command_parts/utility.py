from __future__ import annotations

import random

from quickquip.adapters.nonebot.command_parts.common import _DICE_RE, _NUMBER_EMOJIS, _daily_fortune, _safe_shlex_split, _strip_command_name


def register_utility_commands(on_command, Message, MessageSegment) -> None:
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
